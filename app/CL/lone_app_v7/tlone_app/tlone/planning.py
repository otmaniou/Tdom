"""Module 2 — Planning TL.

Port fidèle du notebook Planning_TL_V15A (VERSION V15A_PART2B_REBUILD_PLANNING_TL_V1) :
mêmes règles, mêmes colonnes, mêmes identifiants (DOM_ID, VERSION_ID, PERIODE_ID).
Ajouts TL-One :
- `exclure_validation_incomplete` (désactivable) écarte un dossier tant qu'une ligne de A_VALIDER_MANUELLEMENT
  n'a pas de décision ;
- bornes du Planning (décision du 23/10/2026) = dates de RÉFÉRENCE validées dans la matrice DOM : ligne « Date
  de début » / « Date de fin » (valeur retenue écrite dans CTS_DATE_DEBUT_VALIDITE_PERMIS / _FIN, comme le V15A) ;
  si la date de fin manque : début + durée retenue (CTS_DUREE_MOIS) − 1 jour ; si le début manque :
  CTS_DATE_DEBUT_CONTRAT. Contrôle CONTROLE_DUREE : nombre de mois planifiés = durée retenue (12, 24…).
  Avec les deux dates présentes, résultat identique au V15A (mêmes VERSION_ID / PERIODE_ID).
"""
from __future__ import annotations

import calendar
import hashlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .common import clean, is_blank, parse_amount, parse_date

VERSION = "V15A_PART2B_REBUILD_PLANNING_TL_V1"
APP_PORT = "TLONE_APP_PLANNING_V1"


def normalize_decision(v):
    if is_blank(v):
        return None
    s = str(v).strip().upper().replace("É", "E")
    mapping = {"VALIDE": "VALIDEE", "VALIDEE": "VALIDEE", "CORRIGE": "CORRIGEE",
               "CORRIGEE": "CORRIGEE", "REJETE": "REJETEE", "REJETEE": "REJETEE"}
    return mapping.get(s, s)


def first_value(row, candidates):
    for c in candidates:
        if c in row.index and not is_blank(row.get(c)):
            return row.get(c)
    return None


def load_param_aug(path: Path) -> tuple[pd.DataFrame, dict]:
    if not path.exists():
        raise FileNotFoundError(f"Fichier paramètre augmentation absent : {path}")
    df = pd.read_excel(path, dtype=object)
    return df, param_aug_map(df)


def param_aug_map(df: pd.DataFrame) -> dict:
    colmap = {str(c).strip().upper(): c for c in df.columns}
    if not {"ANNEE_AUGMENTATION", "MOIS_AUGMENTATION"}.issubset(colmap):
        raise RuntimeError("parametres_augmentation.xlsx doit contenir ANNEE_AUGMENTATION et MOIS_AUGMENTATION")
    out = {}
    for _, r in df.iterrows():
        yv, mv = r[colmap["ANNEE_AUGMENTATION"]], r[colmap["MOIS_AUGMENTATION"]]
        if is_blank(yv) or is_blank(mv):
            continue
        y, m = int(float(yv)), int(float(mv))
        if not 1 <= m <= 12:
            raise ValueError(f"Mois d'augmentation invalide : année={y}, mois={m}")
        out[y] = m
    return out


# --------------------------------------------------------------------------- 2
def apply_manual(dossiers: pd.DataFrame, manuel: pd.DataFrame):
    base = dossiers.copy()
    audit, rejetes = [], set()
    for _, r in manuel.iterrows():
        fichier, champ = clean(r.get("FICHIER")), clean(r.get("CHAMP"))
        decision = normalize_decision(r.get("DECISION_MANUELLE"))
        if fichier is None or champ is None or decision is None:
            continue
        mask = base["FICHIER"].astype(str) == str(fichier)
        if not mask.any():
            audit.append({"FICHIER": fichier, "CHAMP": champ, "DECISION": decision,
                          "STATUT_APPLICATION": "FICHIER_NON_TROUVE"})
            continue
        if decision == "REJETEE":
            rejetes.add(str(fichier))
            audit.append({"FICHIER": fichier, "CHAMP": champ, "DECISION": decision,
                          "STATUT_APPLICATION": "DOSSIER_REJETE"})
            continue
        vv, vp = clean(r.get("VALEUR_VALIDEE")), clean(r.get("VALEUR_PROPOSEE"))
        vn, vr = clean(r.get("NORMALIZED")), clean(r.get("RAW"))
        if decision == "CORRIGEE":
            valeur = vv
            if valeur is None:
                audit.append({"FICHIER": fichier, "CHAMP": champ, "DECISION": decision,
                              "STATUT_APPLICATION": "CORRECTION_SANS_VALEUR_VALIDEE"})
                continue
        else:
            valeur = vv if vv is not None else vp if vp is not None else vn if vn is not None else vr
        if champ not in base.columns:
            base[champ] = None
        ancienne = base.loc[mask, champ].iloc[0]
        if valeur is not None:
            base[champ] = base[champ].astype(object)
            base.loc[mask, champ] = valeur
        audit.append({"FICHIER": fichier, "CHAMP": champ, "DECISION": decision,
                      "ANCIENNE_VALEUR": ancienne, "VALEUR_FINALE": base.loc[mask, champ].iloc[0],
                      "STATUT_APPLICATION": "APPLIQUEE"})
    return base, pd.DataFrame(audit), rejetes


# --------------------------------------------------------------------------- 4
def _reference(r, debut_permis, fin_permis):
    """Début / fin de référence + durée retenue (mois) et origine des dates."""
    from .matrice import add_months, to_months
    n = to_months(r.get("CTS_DUREE_MOIS"))
    debut, src = debut_permis, "REFERENCE"
    if debut is None:
        debut, src = parse_date(r.get("CTS_DATE_DEBUT_CONTRAT")), "DEBUT_CONTRAT (date de début de référence absente)"
    fin = fin_permis
    if fin is None and debut is not None and n:
        fin, src = add_months(debut, int(n)) - timedelta(days=1), src + " + DUREE (date de fin absente)"
    return debut, fin, (int(n) if n else None), src


def build_versions(base: pd.DataFrame, rejetes: set, aug_by_year: dict, incomplets: set):
    versions, rejets = [], []
    for _, r in base.iterrows():
        fichier = str(r.get("FICHIER"))
        if fichier in rejetes:
            rejets.append({"FICHIER": fichier, "MOTIF": "REJETE_EN_PARTIE_2A"})
            continue
        if fichier in incomplets:
            rejets.append({"FICHIER": fichier, "MOTIF": "VALIDATION_HUMAINE_INCOMPLETE"})
            continue
        type_dossier = str(r.get("TYPE_DOSSIER") or "").strip().upper()
        if type_dossier not in ("NOUVEAU_CONTRAT", "AUGMENTATION"):
            rejets.append({"FICHIER": fichier, "MOTIF": "TYPE_DOSSIER_NON_RESOLU"})
            continue
        debut_permis = parse_date(r.get("CTS_DATE_DEBUT_VALIDITE_PERMIS"))
        fin_permis = parse_date(r.get("CTS_DATE_FIN_VALIDITE_PERMIS"))
        salaire_ancien = parse_amount(r.get("CTS_SALAIRE_NET_ANCIEN"))
        salaire_nouveau = parse_amount(r.get("CTS_SALAIRE_NET"))
        part_transferable = parse_amount(r.get("CTS_PART_TRANSFERABLE"))
        compte = first_value(r, ["DOM_COMPTE_LOCAL_NORMALIZED", "DOM_COMPTE_LOCAL"])
        numero_dom = first_value(r, ["NUMERO_DOMICILIATION_VALIDE", "NUMERO_DOMICILIATION_PROPOSE",
                                     "NUMERO_DOMICILIATION_NORMALIZED"])
        motifs = []
        ref_debut, ref_fin, duree_ref, src = _reference(r, debut_permis, fin_permis)
        if ref_debut is None:
            motifs.append("CTS_DATE_DEBUT_VALIDITE_PERMIS_ABSENTE")
        if ref_fin is None:
            motifs.append("CTS_DATE_FIN_VALIDITE_PERMIS_ABSENTE")
        if ref_debut and ref_fin and ref_fin < ref_debut:
            motifs.append("FIN_PERMIS_AVANT_DEBUT")
        if salaire_nouveau is None:
            motifs.append("CTS_SALAIRE_NET_ABSENT")
        if part_transferable is None:
            motifs.append("CTS_PART_TRANSFERABLE_ABSENTE")
        if is_blank(compte):
            motifs.append("COMPTE_FINAL_ABSENT")
        if is_blank(numero_dom):
            motifs.append("NUMERO_DOMICILIATION_FINAL_ABSENT")

        annee_aug = mois_aug = None
        if type_dossier == "NOUVEAU_CONTRAT":
            date_effet = ref_debut
        else:
            if not is_blank(r.get("AUGMENTATION_YEAR")):
                try:
                    annee_aug = int(float(r.get("AUGMENTATION_YEAR")))
                except Exception:
                    annee_aug = None
            if annee_aug is None:
                ddoc = parse_date(r.get("CTS_DATE_DOCUMENT"))
                if ddoc:
                    annee_aug = ddoc.year
            if annee_aug is not None:
                mois_aug = aug_by_year.get(annee_aug)
            if annee_aug is None or mois_aug is None:
                date_effet = None
                motifs.append("PERIODE_AUGMENTATION_PARAMETREE_ABSENTE")
            else:
                date_effet = date(annee_aug, mois_aug, 1)
        if motifs:
            rejets.append({"FICHIER": fichier, "MOTIF": " | ".join(motifs)})
            continue
        dom_key = f"{str(numero_dom).strip()}|{str(compte).strip()}"
        dom_id = hashlib.sha256(dom_key.encode("utf-8")).hexdigest()[:20]
        versions.append({
            "DOM_ID": dom_id, "FICHIER": fichier, "NUMERO_DOMICILIATION": numero_dom,
            "DOM_COMPTE_LOCAL": compte, "SIEGE_RACINE": r.get("SIEGE_RACINE"),
            "TYPE_VERSION": type_dossier, "DATE_EFFET_VERSION": date_effet,
            "ANNEE_AUGMENTATION": annee_aug, "MOIS_AUGMENTATION_PARAMETRE": mois_aug,
            "CTS_REFERENCE_DOCUMENT": r.get("CTS_REFERENCE_DOCUMENT"),
            "CTS_NOM_PRENOM_TRAVAILLEUR": r.get("CTS_NOM_PRENOM_TRAVAILLEUR"),
            "CTS_NUMERO_PERMIS_TRAVAIL": r.get("CTS_NUMERO_PERMIS_TRAVAIL"),
            "CTS_DATE_DEBUT_VALIDITE_PERMIS": debut_permis, "CTS_DATE_FIN_VALIDITE_PERMIS": fin_permis,
            "CTS_SALAIRE_NET_ANCIEN": salaire_ancien, "CTS_SALAIRE_NET": salaire_nouveau,
            "CTS_PART_TRANSFERABLE": part_transferable,
            "CTS_PART_PAYABLE_DZD": parse_amount(r.get("CTS_PART_PAYABLE_DZD")),
            "CTS_DATE_DOCUMENT": parse_date(r.get("CTS_DATE_DOCUMENT")),
            "DQ_SCORE": r.get("DQ_SCORE"), "DOSSIER_STATUS": r.get("DOSSIER_STATUS"),
            "DATE_DEBUT_REFERENCE": ref_debut, "DATE_FIN_REFERENCE": ref_fin, "DUREE_REFERENCE_MOIS": duree_ref,
            "BASE_DATES": src,
        })
    return pd.DataFrame(versions), pd.DataFrame(rejets, columns=["FICHIER", "MOTIF"])


# --------------------------------------------------------------------------- 5
def number_augmentations(v: pd.DataFrame) -> pd.DataFrame:
    if v.empty:
        return v
    v = v.copy()
    v["_ORDRE_TYPE"] = v["TYPE_VERSION"].map({"NOUVEAU_CONTRAT": 0, "AUGMENTATION": 1})
    v = v.sort_values(["DOM_ID", "DATE_EFFET_VERSION", "_ORDRE_TYPE", "FICHIER"]).reset_index(drop=True)
    v["NUMERO_AUGMENTATION"] = 0
    v["NOMBRE_TOTAL_AUGMENTATIONS"] = 0
    for _, idx in v.groupby("DOM_ID").groups.items():
        idx, n = list(idx), 0
        for i in idx:
            if v.at[i, "TYPE_VERSION"] == "AUGMENTATION":
                n += 1
                v.at[i, "NUMERO_AUGMENTATION"] = n
        for i in idx:
            v.at[i, "NOMBRE_TOTAL_AUGMENTATIONS"] = n
    return v.drop(columns=["_ORDRE_TYPE"])


# --------------------------------------------------------------------------- 6
def apply_windows(v: pd.DataFrame):
    windows, rej = [], []
    if v.empty:
        return pd.DataFrame(), pd.DataFrame(columns=["FICHIER", "MOTIF"])
    for dom_id, group in v.groupby("DOM_ID", sort=False):
        group = group.sort_values(["DATE_EFFET_VERSION", "NUMERO_AUGMENTATION", "FICHIER"]).reset_index(drop=True)
        for i, row in group.iterrows():
            start = max(row["DATE_EFFET_VERSION"], row["DATE_DEBUT_REFERENCE"])
            end = row["DATE_FIN_REFERENCE"]
            if i + 1 < len(group):
                end = min(end, group.loc[i + 1, "DATE_EFFET_VERSION"] - timedelta(days=1))
            if end < start:
                rej.append({"FICHIER": row["FICHIER"], "MOTIF": "FENETRE_VERSION_VIDE_APRES_DECOUPAGE"})
                continue
            d = row.to_dict()
            d["DATE_DEBUT_APPLICABLE"], d["DATE_FIN_APPLICABLE"] = start, end
            d["VERSION_ID"] = hashlib.sha256(
                f'{dom_id}|{row["FICHIER"]}|{row["TYPE_VERSION"]}|'
                f'{row["NUMERO_AUGMENTATION"]}|{start.isoformat()}'.encode("utf-8")).hexdigest()[:24]
            windows.append(d)
    return pd.DataFrame(windows), pd.DataFrame(rej, columns=["FICHIER", "MOTIF"])


# --------------------------------------------------------------------------- 7
def generate_periods(row: dict) -> list[dict]:
    start, end = row["DATE_DEBUT_APPLICABLE"], row["DATE_FIN_APPLICABLE"]
    cursor = date(start.year, start.month, 1)
    rows = []
    while cursor <= end:
        nb_jours_mois = calendar.monthrange(cursor.year, cursor.month)[1]
        fin_mois = date(cursor.year, cursor.month, nb_jours_mois)
        seg_start, seg_end = max(start, cursor), min(end, fin_mois)
        if seg_start <= seg_end:
            mois_complet = seg_start == cursor and seg_end == fin_mois
            if mois_complet:
                partie, periode = None, f"{cursor.year:04d}-{cursor.month:02d}"
            elif seg_start.day == 1:
                partie, periode = "P1", f"{cursor.year:04d}-{cursor.month:02d}P1"
            else:
                partie, periode = "P2", f"{cursor.year:04d}-{cursor.month:02d}P2"
            nb_jours = (seg_end - seg_start).days + 1
            coefficient = nb_jours / nb_jours_mois
            plafond = row["CTS_PART_TRANSFERABLE"]
            period_id = hashlib.sha256(f'{row["VERSION_ID"]}|{periode}'.encode("utf-8")).hexdigest()[:24]
            rows.append({
                "PERIODE_ID": period_id, "DOM_ID": row["DOM_ID"], "VERSION_ID": row["VERSION_ID"],
                "FICHIER_SOURCE": row["FICHIER"], "NUMERO_DOMICILIATION": row["NUMERO_DOMICILIATION"],
                "DOM_COMPTE_LOCAL": row["DOM_COMPTE_LOCAL"], "SIEGE_RACINE": row.get("SIEGE_RACINE"),
                "NOM_TRAVAILLEUR": row.get("CTS_NOM_PRENOM_TRAVAILLEUR"),
                "NUMERO_PERMIS_TRAVAIL": row.get("CTS_NUMERO_PERMIS_TRAVAIL"),
                "CTS_REFERENCE_DOCUMENT": row.get("CTS_REFERENCE_DOCUMENT"),
                "TYPE_VERSION": row["TYPE_VERSION"],
                "NUMERO_AUGMENTATION": int(row["NUMERO_AUGMENTATION"]),
                "NOMBRE_TOTAL_AUGMENTATIONS": int(row["NOMBRE_TOTAL_AUGMENTATIONS"]),
                "ANNEE_AUGMENTATION": row.get("ANNEE_AUGMENTATION"),
                "MOIS_AUGMENTATION_PARAMETRE": row.get("MOIS_AUGMENTATION_PARAMETRE"),
                "DATE_EFFET_VERSION": row["DATE_EFFET_VERSION"].isoformat(),
                "DATE_DEBUT_VALIDITE_PERMIS": _iso(row.get("CTS_DATE_DEBUT_VALIDITE_PERMIS")),
                "DATE_FIN_VALIDITE_PERMIS": _iso(row.get("CTS_DATE_FIN_VALIDITE_PERMIS")),
                "DATE_DEBUT_APPLICABLE": start.isoformat(), "DATE_FIN_APPLICABLE": end.isoformat(),
                "PERIODE_TL": periode, "MOIS_BASE": f"{cursor.year:04d}-{cursor.month:02d}",
                "PARTIE": partie, "DATE_DEBUT_SEGMENT": seg_start.isoformat(),
                "DATE_FIN_SEGMENT": seg_end.isoformat(), "NB_JOURS_SEGMENT": nb_jours,
                "NB_JOURS_MOIS": nb_jours_mois, "COEFFICIENT_PRORATA": round(coefficient, 8),
                "SALAIRE_NET_ANCIEN_CTS": row.get("CTS_SALAIRE_NET_ANCIEN"),
                "SALAIRE_NET_NOUVEAU_CTS": row.get("CTS_SALAIRE_NET"),
                "SALAIRE_NET_APPLICABLE": row.get("CTS_SALAIRE_NET"),
                "PART_TRANSFERABLE_CTS": plafond,
                "MONTANT_MAX_THEORIQUE": round(plafond * coefficient, 2),
                "ATF_REFERENCE": None, "AUTORISATION_REFERENCE": None, "MONTANT_AUTORISE_SAISI": None,
                "MONTANT_TRANSFERE": None, "SOLDE_RESTANT": None, "DATE_EXECUTION_TL": None,
                "STATUT_PERIODE": "BASE_THEORIQUE_CTS", "MOTIF_REJET": None,
                "DATE_DEBUT_REFERENCE": _iso(row.get("DATE_DEBUT_REFERENCE")),
                "DATE_FIN_REFERENCE": _iso(row.get("DATE_FIN_REFERENCE")),
                "DUREE_REFERENCE_MOIS": row.get("DUREE_REFERENCE_MOIS"),
                "BASE_DATES": row.get("BASE_DATES"),
            })
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    return rows


def _iso(d) -> str | None:
    return d.isoformat() if isinstance(d, date) else None


def controle_duree(planning: pd.DataFrame, versions: pd.DataFrame) -> pd.DataFrame:
    """Par domiciliation : mois planifiés (du début à la fin de référence) face à la durée retenue (12, 24…)."""
    cols = ["DOM_ID", "NOM_TRAVAILLEUR", "NUMERO_DOMICILIATION", "DATE_DEBUT_REFERENCE", "DATE_FIN_REFERENCE",
            "DUREE_REFERENCE_MOIS", "MOIS_PLANIFIES", "CONTROLE_DUREE", "PREMIERE_VERSION"]
    if planning is None or planning.empty or versions is None or versions.empty:
        return pd.DataFrame(columns=cols)
    from .matrice import months_between
    out = []
    for dom, g in planning.groupby("DOM_ID", sort=False):
        v = versions[versions["DOM_ID"] == dom].sort_values("DATE_EFFET_VERSION")
        nc = v[v["TYPE_VERSION"] == "NOUVEAU_CONTRAT"]
        ref = (nc if not nc.empty else v).iloc[0]
        d0, d1, n = ref["DATE_DEBUT_REFERENCE"], ref["DATE_FIN_REFERENCE"], ref["DUREE_REFERENCE_MOIS"]
        mois = months_between(date.fromisoformat(g["DATE_DEBUT_SEGMENT"].min()), date.fromisoformat(g["DATE_FIN_SEGMENT"].max()))
        if nc.empty:
            ctl = "SANS_CONTRAT_INITIAL : Planning à partir de l'augmentation (valider le contrat initial)"
        elif n is None or pd.isna(n):
            ctl = "DUREE_ABSENTE"
        else:
            ctl = "OK" if int(n) == mois else f"ECART : {mois} mois planifiés / {int(n)} mois de durée de référence"
        out.append({"DOM_ID": dom, "NOM_TRAVAILLEUR": g["NOM_TRAVAILLEUR"].iloc[0],
                    "NUMERO_DOMICILIATION": g["NUMERO_DOMICILIATION"].iloc[0],
                    "DATE_DEBUT_REFERENCE": _iso(d0), "DATE_FIN_REFERENCE": _iso(d1),
                    "DUREE_REFERENCE_MOIS": None if n is None or pd.isna(n) else int(n), "MOIS_PLANIFIES": mois,
                    "CONTROLE_DUREE": ctl, "PREMIERE_VERSION": ref["TYPE_VERSION"]})
    return pd.DataFrame(out, columns=cols)


def dq_checks(planning: pd.DataFrame) -> list[str]:
    errs = []
    if planning.empty:
        return errs
    if planning["PERIODE_ID"].duplicated().any():
        errs.append("PERIODE_ID_DUPLIQUE")
    if ((planning["COEFFICIENT_PRORATA"] <= 0) | (planning["COEFFICIENT_PRORATA"] > 1)).any():
        errs.append("COEFFICIENT_PRORATA_INVALIDE")
    if planning.duplicated(["VERSION_ID", "PERIODE_TL"], keep=False).any():
        errs.append("VERSION_PERIODE_DUPLIQUEE")
    return errs


def build_planning(dossiers: pd.DataFrame, manuel: pd.DataFrame, param_aug: pd.DataFrame,
                   exclure_validation_incomplete: bool = False, fichiers_valides: set | None = None) -> dict:
    """`fichiers_valides` : si fourni, seuls ces dossiers (validés dans la matrice) sont planifiés ;
    les autres sortent en rejet VALIDATION_HUMAINE_INCOMPLETE."""
    if "FICHIER" not in dossiers.columns:
        raise RuntimeError("Colonne FICHIER absente de DOSSIERS_A_VALIDER")
    aug = param_aug_map(param_aug)
    base, audit, rejetes = apply_manual(dossiers, manuel)
    incomplets: set = set()
    if exclure_validation_incomplete and not manuel.empty:
        und = manuel[manuel["DECISION_MANUELLE"].map(normalize_decision).isna()]
        incomplets = set(und["FICHIER"].astype(str)) - rejetes
    if fichiers_valides is not None:
        incomplets |= set(dossiers["FICHIER"].astype(str)) - set(map(str, fichiers_valides)) - rejetes
    versions, rejets = build_versions(base, rejetes, aug, incomplets)
    versions = number_augmentations(versions)
    applicables, rej_w = apply_windows(versions)
    rejets = pd.concat([rejets, rej_w], ignore_index=True)
    rows = []
    for _, r in applicables.iterrows():
        rows.extend(generate_periods(r.to_dict()))
    planning = pd.DataFrame(rows)
    if not planning.empty:
        planning = planning.sort_values(["DOM_ID", "DATE_DEBUT_SEGMENT", "NUMERO_AUGMENTATION"]).reset_index(drop=True)
    regles = pd.DataFrame([
        ["VERSION", VERSION], ["PORTAGE_APP", APP_PORT],
        ["SOURCE", "validation_domiciliations_V15_A.xlsx corrigé"],
        ["REFERENCE_METIER", "CTS corrigé/validé Partie 2A"],
        ["COMPTE", "Valeur finale Partie 2A"], ["NUMERO_DOMICILIATION", "Valeur finale/validée Partie 2A"],
        ["BORNES_PLANNING", "Date de début / Date de fin de référence validées dans la matrice DOM "
         "(CTS_DATE_DEBUT_VALIDITE_PERMIS / CTS_DATE_FIN_VALIDITE_PERMIS) ; fin absente : début + durée − 1 jour"],
        ["CONTROLE_DUREE", "Nombre de mois planifiés = durée de référence (CTS_DUREE_MOIS)"],
        ["SALAIRE_ANCIEN", "CTS_SALAIRE_NET_ANCIEN"], ["SALAIRE_NOUVEAU", "CTS_SALAIRE_NET"],
        ["PART_TRANSFERABLE", "CTS_PART_TRANSFERABLE"], ["TYPE_VERSION", "NOUVEAU_CONTRAT / AUGMENTATION"],
        ["NUMERO_AUGMENTATION", "0 nouveau contrat; 1,2,3... augmentations"],
        ["NOMBRE_TOTAL_AUGMENTATIONS", "Nombre total d'augmentations de la domiciliation"],
        ["PERIODE_AUGMENTATION", "ANNEE_AUGMENTATION + MOIS_AUGMENTATION du fichier paramètre"],
        ["DATE_EFFET_AUGMENTATION", "Premier jour du mois paramétré"],
        ["REGLE_REMPLACEMENT", "Nouvelle version coupe la précédente la veille de sa date d'effet"],
        ["PRORATA", "NB_JOURS_SEGMENT / NB_JOURS_MOIS"],
        ["EXCLUSION_VALIDATION_INCOMPLETE", str(bool(exclure_validation_incomplete))],
        ["SEULEMENT_DOSSIERS_VALIDES_MATRICE", str(fichiers_valides is not None)],
        ["ATF_AUTORISATIONS", "Contrôlés au Module 3 (transferts)"],
    ], columns=["PARAMETRE", "REGLE"])
    controles = controle_duree(planning, applicables)
    return {"Planning_TL": planning, "BASE_VERSIONS_CTS": applicables, "CORRECTIONS_APPLIQUEES": audit,
            "PARAM_AUGMENTATION": param_aug, "REJETS_PLANNING": rejets, "REGLES": regles,
            "CONTROLE_DUREE": controles,
            "_dq": dq_checks(planning)}


def export(result: dict, out_xlsx: Path, out_csv: Path) -> None:
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    result["Planning_TL"].to_csv(out_csv, index=False, encoding="utf-8-sig")
    result["BASE_VERSIONS_CTS"].to_csv(out_xlsx.parent / "Base_versions_CTS_V15A.csv", index=False, encoding="utf-8-sig")
    result["REJETS_PLANNING"].to_csv(out_xlsx.parent / "Rejets_Planning_TL_V15A.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as w:
        for k in ("Planning_TL", "BASE_VERSIONS_CTS", "CONTROLE_DUREE", "CORRECTIONS_APPLIQUEES",
                  "PARAM_AUGMENTATION", "REJETS_PLANNING", "REGLES"):
            if k not in result:
                continue
            result[k].to_excel(w, sheet_name=k, index=False)


def load_planning(path_csv: Path) -> pd.DataFrame:
    if not path_csv.exists() or path_csv.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path_csv, dtype={"DOM_COMPTE_LOCAL": str, "SIEGE_RACINE": str,
                                            "NUMERO_DOMICILIATION": str, "PARTIE": str}, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:  # planning exporté sans aucune période
        return pd.DataFrame()


MOTIFS_LISIBLES = {
    "REJETE_EN_PARTIE_2A": "Dossier rejeté",
    "VALIDATION_HUMAINE_INCOMPLETE": "Dossier pas encore validé dans la matrice DOM",
    "NON_VALIDE_MATRICE": "Dossier pas encore validé dans la matrice DOM",
    "TYPE_DOSSIER_NON_RESOLU": "Type inconnu (nouveau contrat ou augmentation ?)",
    "CTS_DATE_DEBUT_VALIDITE_PERMIS_ABSENTE": "Date de début absente",
    "CTS_DATE_FIN_VALIDITE_PERMIS_ABSENTE": "Date de fin absente",
    "FIN_PERMIS_AVANT_DEBUT": "Date de fin avant la date de début",
    "CTS_SALAIRE_NET_ABSENT": "Salaire net absent",
    "CTS_PART_TRANSFERABLE_ABSENTE": "Part transférable absente",
    "COMPTE_FINAL_ABSENT": "Compte du salarié absent",
    "NUMERO_DOMICILIATION_FINAL_ABSENT": "N° de domiciliation absent",
    "PERIODE_AUGMENTATION_PARAMETREE_ABSENTE": "Année de l'augmentation absente du calendrier des augmentations "
                                               "(Domiciliations › Paramètres, vue experte)",
    "FENETRE_VERSION_VIDE_APRES_DECOUPAGE": "Remplacé entièrement par une version plus récente (augmentation)",
}


def motif_lisible(m) -> str:
    """Motif de rejet du Planning en langage courant (plusieurs motifs séparés par « | »)."""
    parts = [p.strip() for p in str(m or "").split("|") if p.strip()]
    return " · ".join(MOTIFS_LISIBLES.get(p, p) for p in parts) or "—"
