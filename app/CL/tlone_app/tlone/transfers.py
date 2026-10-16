"""Module 3 — Contrôles des dossiers de transfert (OV / Annexe I / Annexe II / Bulletin).

Entrée  : classeur audit_transferts_*.xlsx produit par le notebook v26 (extraction VLM)
          + Planning_TL (Module 2) + référentiels ATF / autorisations (optionnels)
          + registre des TL déjà validés.
Sortie  : une synthèse par dossier, le détail des contrôles, puis un registre.

Principe (hérité de la Partie 2) : une valeur OCR absente ou illisible n'est JAMAIS
un motif de rejet automatique -> REVIEW. Seul un écart objectivable sur des valeurs
lues (plafond dépassé, doublon, autorisation échue...) est BLOQUANT. La décision
finale reste humaine.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .common import (digits, dom_ref_compact, is_blank, name_similarity, parse_amount,
                     parse_date, siege_racine)
from .montant_lettres import lettres_to_number

# Schéma du classeur v26 (cellule « Export Excel ») : (groupe, clé, libellé)
V26_SCHEMA = {
    "META": [("fichier", "Fichier"), ("date_traitement", "Date traitement"),
             ("pages_trouvees", "Pages trouvées"), ("pages_manquantes", "Pages manquantes"),
             ("anomalies", "Anomalies")],
    "OV": [("monnaie", "Monnaie"), ("montant_chiffres", "Montant (chiffres)"),
           ("montant_lettres", "Montant (lettres)"), ("periode", "Période"), ("tranche", "Tranche"),
           ("date_demande", "Date demande"), ("compte_debiteur", "Compte débiteur"),
           ("beneficiaire_nom", "Bénéficiaire nom"), ("beneficiaire_compte", "Bénéficiaire compte"),
           ("beneficiaire_adresse", "Bénéficiaire adresse"), ("swift", "SWIFT"),
           ("banque_nom", "Banque bénéficiaire"), ("status", "Statut"),
           ("validation_errors", "Erreurs validation")],
    "ANNEXE_I": [("nom_prenom", "Nom Prénom"), ("date_signature", "Date signature"),
                 ("status", "Statut"), ("validation_errors", "Erreurs validation")],
    "ANNEXE_II": [("mois_transfert", "Mois transfert"), ("nom_prenom", "Nom Prénom"),
                  ("compte_bancaire", "Compte bancaire"), ("salaire_mensuel", "Salaire mensuel"),
                  ("nombre_jours", "Nombre de jours"), ("part_transferable", "Part transférable"),
                  ("pays_destination", "Pays destination"), ("compte_devise", "Compte devise"),
                  ("numero_domiciliation", "N° domiciliation"),
                  ("date_domiciliation", "Date domiciliation"), ("status", "Statut"),
                  ("validation_errors", "Erreurs validation")],
    "BULLETIN": [("nom_prenom", "Nom Prénom"), ("matricule", "Matricule"),
                 ("mois_bulletin", "Mois bulletin"), ("salaire_base", "Salaire base"),
                 ("salaire_brut", "Salaire brut"), ("retenue_ss", "Retenue SS"),
                 ("retenue_irg", "Retenue IRG"), ("retenue_mutuelle", "Retenue mutuelle"),
                 ("net_a_payer", "Net à payer")],
}

MOIS = {"JANVIER": 1, "FEVRIER": 2, "MARS": 3, "AVRIL": 4, "MAI": 5, "JUIN": 6, "JUILLET": 7,
        "AOUT": 8, "SEPTEMBRE": 9, "OCTOBRE": 10, "NOVEMBRE": 11, "DECEMBRE": 12,
        "JAN": 1, "FEV": 2, "AVR": 4, "JUIL": 7, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12}

ATF_COLUMNS = ["NOM_PRENOM", "COMPTE", "MOIS", "SALAIRE_NET", "IRG", "MONTANT_TRANSFERABLE", "ATF_REFERENCE"]
AUT_COLUMNS = ["NOM_PRENOM", "COMPTE", "MOIS", "MONTANT_AUTORISE", "DATE_VALIDATION", "DATE_LIMITE",
               "AUTORISATION_REFERENCE"]
REQUIRED = {"ATF": ["NOM_PRENOM", "MOIS", "MONTANT_TRANSFERABLE"],
            "Autorisations": ["NOM_PRENOM", "MOIS", "MONTANT_AUTORISE"]}
REGISTRE_COLUMNS = ["TL_ID", "FICHIER", "DOM_ID", "PERIODE_ID", "PERIODE_TL", "SIEGE_RACINE", "NOM",
                    "NUMERO_DOMICILIATION", "MONTANT", "DEVISE", "PROVISION_ATLAS", "STATUT_CONTROLE",
                    "DECISION", "COMMENTAIRE", "VALIDE_PAR", "DATE_VALIDATION", "STATUT_EXECUTION"]


# ------------------------------------------------------------------ lecture v26
def read_audit_xlsx(path: Path) -> pd.DataFrame:
    """Aplatis le classeur à double en-tête en colonnes « GROUPE.clé »."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb["Dossiers"] if "Dossiers" in wb.sheetnames else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return pd.DataFrame()
    groups, g = [], None
    for v in rows[0]:
        g = v if v not in (None, "") else g
        groups.append(g)
    label_to_key = {(grp, lab): key for grp, cols in V26_SCHEMA.items() for key, lab in cols}
    cols = []
    for grp, lab in zip(groups, rows[1]):
        key = label_to_key.get((grp, lab), re.sub(r"\W+", "_", str(lab or "")).lower())
        cols.append(key if grp == "META" else f"{grp}.{key}")
    df = pd.DataFrame([r for r in rows[2:] if any(x is not None for x in r)], columns=cols)
    df["AUDIT_SOURCE"] = path.name
    return df


def latest_audit(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(folder.glob("audit_transferts_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)


# ------------------------------------------------------------------ périodes
def parse_periode(v) -> tuple[str | None, str | None]:
    """'MARS 2026 PART 1' -> ('2026-03','P1') ; '03/2026' -> ('2026-03', None)."""
    if is_blank(v):
        return None, None
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", str(v)) if not unicodedata.combining(c)).upper()
    part = None
    m = re.search(r"(?:PART(?:IE)?|P|TRANCHE)\s*([12])\b", s)
    if m:
        part = f"P{m.group(1)}"
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})\b", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}", part
    m = re.search(r"\b(\d{1,2})[-/.](\d{4})\b", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}", part
    year = re.search(r"\b(20\d{2})\b", s)
    month = None
    for name, num in sorted(MOIS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{name}\b", s):
            month = num
            break
    if year and month:
        return f"{int(year.group(1)):04d}-{month:02d}", part
    return None, part


def periode_from_filename(name: str) -> tuple[str | None, str | None]:
    m = re.search(r"(20\d{2})(0[1-9]|1[0-2])(P[12])?$", Path(str(name)).stem.upper())
    if not m:
        return None, None
    return f"{m.group(1)}-{m.group(2)}", m.group(3)


def periode_label(mois: str | None, part: str | None) -> str | None:
    if not mois:
        return None
    return mois + (part or "")


# ------------------------------------------------------------------ référentiels
def load_referential(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path or not Path(path).exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_excel(path, dtype=object)
    df.columns = [str(c).strip().upper() for c in df.columns]
    for c in columns:
        if c not in df.columns:
            df[c] = None
    df["_MOIS"] = df["MOIS"].map(lambda v: parse_periode(v)[0])
    df["_COMPTE"] = df["COMPTE"].map(digits)
    return df


def template(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _match_ref(ref: pd.DataFrame, mois: str | None, compte: str, nom, seuil: float):
    if ref is None or ref.empty or not mois:
        return None, None
    cand = ref[ref["_MOIS"] == mois]
    if cand.empty:
        return None, None
    if compte:
        by_compte = cand[cand["_COMPTE"] == compte]
        if not by_compte.empty:
            return by_compte.iloc[0], "COMPTE"
    best, best_s = None, 0.0
    for _, r in cand.iterrows():
        sim = name_similarity(nom, r.get("NOM_PRENOM")) or 0.0
        if sim > best_s:
            best, best_s = r, sim
    if best is not None and best_s >= seuil:
        return best, f"NOM ({best_s:.2f})"
    return None, None


# ------------------------------------------------------------------ registre
def load_registre(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=REGISTRE_COLUMNS)
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").reindex(columns=REGISTRE_COLUMNS)


def _registre_valide(reg: pd.DataFrame) -> pd.DataFrame:
    if reg.empty:
        return reg
    r = reg[reg["DECISION"].fillna("") == "VALIDE"].copy()
    r["_MONTANT"] = r["MONTANT"].map(parse_amount).fillna(0.0)
    return r


def tl_id(fichier: str, periode_id: str | None) -> str:
    return hashlib.sha256(f"{fichier}|{periode_id or ''}".encode()).hexdigest()[:20]


# ------------------------------------------------------------------ contrôles
class _Checks:
    def __init__(self, fichier: str):
        self.fichier, self.rows = fichier, []

    def add(self, code, libelle, ref, severite, resultat, detail=""):
        self.rows.append({"FICHIER": self.fichier, "CODE": code, "CONTROLE": libelle, "REFERENCE": ref,
                          "SEVERITE": severite, "RESULTAT": resultat, "DETAIL": detail})

    def cmp_cap(self, code, libelle, ref, montant, cap, tol, missing_msg, severite_missing="REVIEW"):
        if montant is None:
            self.add(code, libelle, ref, "REVIEW", "NON_CONTROLABLE", "Montant OV illisible")
        elif cap is None:
            self.add(code, libelle, ref, severite_missing, "NON_CONTROLABLE", missing_msg)
        elif montant <= cap + tol:
            self.add(code, libelle, ref, "BLOQUANT", "OK", f"{montant:,.2f} ≤ {cap:,.2f}")
        else:
            self.add(code, libelle, ref, "BLOQUANT", "KO", f"{montant:,.2f} > {cap:,.2f} (écart {montant - cap:,.2f})")


def _g(d: dict, k: str):
    v = d.get(k)
    return None if is_blank(v) else v


def control_dossier(d: dict, planning: pd.DataFrame, reg_ok: pd.DataFrame, atf: pd.DataFrame,
                    aut: pd.DataFrame, s, today: date | None = None) -> tuple[dict, list[dict]]:
    today = today or date.today()
    fichier = str(d.get("fichier"))
    ck = _Checks(fichier)
    tol = s.tolerance_montant_dzd

    # ---------- T01 pièces
    manq = [x.strip() for x in str(_g(d, "pages_manquantes") or "").split(",") if x.strip()]
    bloq = [x for x in manq if x in ("OV", "ANNEXE_II", "BULLETIN")]
    ck.add("T01", "Pièces du dossier présentes", "REG-11 / REG-12 / AS-04",
           "BLOQUANT" if bloq else ("REVIEW" if manq else "BLOQUANT"),
           "KO" if manq else "OK", ("Manquantes : " + ", ".join(manq)) if manq else "OV, Annexe I, Annexe II, Bulletin")
    if _g(d, "anomalies") is not None:
        ck.add("T01b", "Pages en doublon", "AS-04", "REVIEW", "KO", str(d.get("anomalies")))

    # ---------- T02 mentions obligatoires OV
    oblig = {"OV.montant_chiffres": "montant", "OV.montant_lettres": "montant en lettres",
             "OV.periode": "période", "OV.compte_debiteur": "compte débiteur",
             "OV.beneficiaire_nom": "bénéficiaire", "OV.beneficiaire_compte": "compte bénéficiaire",
             "OV.swift": "SWIFT", "OV.banque_nom": "banque"}
    absents = [lab for k, lab in oblig.items() if _g(d, k) is None]
    ck.add("T02", "Mentions obligatoires OV lues", "CTL-09", "REVIEW", "KO" if absents else "OK",
           ("Non lues (OCR ou absentes) : " + ", ".join(absents)) if absents else "Toutes lues")

    montant = parse_amount(_g(d, "OV.montant_chiffres"))
    devise = (str(_g(d, "OV.monnaie") or "")).upper() or None

    # ---------- T03 chiffres / lettres
    ml = lettres_to_number(_g(d, "OV.montant_lettres"))
    if montant is None or _g(d, "OV.montant_lettres") is None:
        ck.add("T03", "Montant chiffres = lettres", "CTL-09", "REVIEW", "NON_CONTROLABLE", "Une des deux mentions non lue")
    elif ml is None:
        ck.add("T03", "Montant chiffres = lettres", "CTL-09", "REVIEW", "NON_CONTROLABLE",
               f"Lettres non interprétables : « {_g(d, 'OV.montant_lettres')} »")
    else:
        ok = abs(ml - montant) <= tol
        ck.add("T03", "Montant chiffres = lettres", "CTL-09", "BLOQUANT", "OK" if ok else "KO",
               f"chiffres {montant:,.2f} / lettres {ml:,.2f}")

    # ---------- T17 devise
    if not devise:
        ck.add("T17", "Devise de l'OV", "AS-04", "REVIEW", "NON_CONTROLABLE", "non lue")
    elif devise in ("DZD", "DA"):
        ck.add("T17", "Devise de l'OV", "AS-04", "REVIEW", "OK", devise)
    else:
        ck.add("T17", "Devise de l'OV", "AS-04", "REVIEW", "KO", f"{devise} — plafonds exprimés en DZD, conversion à vérifier")

    # ---------- Périodes
    p_ov = parse_periode(_g(d, "OV.periode"))
    if not p_ov[1] and _g(d, "OV.tranche"):
        p_ov = (p_ov[0], parse_periode("P " + str(_g(d, "OV.tranche")))[1])
    p_a2 = parse_periode(_g(d, "ANNEXE_II.mois_transfert"))
    p_bu = parse_periode(_g(d, "BULLETIN.mois_bulletin"))
    p_fn = periode_from_filename(fichier)
    mois = p_ov[0] or p_a2[0] or p_fn[0]
    part = p_ov[1] or p_a2[1] or p_fn[1]
    vus = {"OV": p_ov[0], "Annexe II": p_a2[0], "Bulletin": p_bu[0], "Nom fichier": p_fn[0]}
    distincts = {v for v in vus.values() if v}
    ck.add("T07", "Période cohérente entre pièces", "CTL-11 / CTL-12", "REVIEW",
           "OK" if len(distincts) == 1 else ("NON_CONTROLABLE" if not distincts else "KO"),
           " | ".join(f"{k}={v or '?'}" for k, v in vus.items()) + (f" | partie={part}" if part else ""))

    # ---------- Comptes / siège
    c_ov = digits(_g(d, "OV.compte_debiteur"))
    c_a2 = digits(_g(d, "ANNEXE_II.compte_bancaire"))
    siege = siege_racine(c_ov) or siege_racine(c_a2) or siege_racine(Path(fichier).stem)

    # ---------- T04 rattachement Planning
    prow, plan_dom = None, pd.DataFrame()
    if planning is not None and not planning.empty:
        pl = planning
        cand = pl[pl["SIEGE_RACINE"].astype(str) == str(siege)] if siege else pl.iloc[0:0]
        if cand.empty and (c_ov or c_a2):
            cand = pl[pl["DOM_COMPTE_LOCAL"].map(digits).isin([x for x in (c_ov, c_a2) if x])]
        plan_dom = cand
        if not cand.empty and mois:
            m = cand[cand["MOIS_BASE"] == mois]
            parties = m["PARTIE"].fillna("").astype(str)
            if part and (parties == part).any():
                m = m[parties == part]
            elif len(m) > 1 and (parties == "").any():
                m = m[parties == ""]
            if len(m) == 1:
                prow = m.iloc[0]
            elif len(m) > 1:
                ck.add("T04", "Rattachement au Planning TL", "AS-04 / AS-07", "REVIEW", "KO",
                       f"Période {mois} fractionnée ({', '.join(m['PERIODE_TL'])}) : préciser la partie sur l'OV")
    if prow is not None:
        ck.add("T04", "Rattachement au Planning TL", "AS-04", "BLOQUANT", "OK",
               f"{prow['PERIODE_TL']} — DOM {prow['NUMERO_DOMICILIATION']}")
    elif not any(r["CODE"] == "T04" for r in ck.rows):
        if planning is None or planning.empty:
            detail = "Planning TL non généré"
        elif plan_dom.empty:
            detail = f"Aucune domiciliation planifiée pour siège {siege or '?'} / compte {c_ov or c_a2 or '?'}"
        else:
            detail = (f"DOM trouvée mais période {periode_label(mois, part) or '?'} hors fenêtre "
                      f"({plan_dom['PERIODE_TL'].iloc[0]} → {plan_dom['PERIODE_TL'].iloc[-1]})")
        ck.add("T04", "Rattachement au Planning TL", "AS-04", "BLOQUANT", "KO", detail)

    # ---------- T05 comptes
    c_dom = digits(prow["DOM_COMPTE_LOCAL"]) if prow is not None else ""
    vals = {"OV": c_ov, "Annexe II": c_a2, "DOM": c_dom}
    present = {k: v for k, v in vals.items() if v}
    if len(present) < 2:
        ck.add("T05", "Compte local identique OV / Annexe II / DOM", "CTL-17", "REVIEW", "NON_CONTROLABLE",
               " | ".join(f"{k}={v or '?'}" for k, v in vals.items()))
    else:
        ok = len(set(present.values())) == 1
        ck.add("T05", "Compte local identique OV / Annexe II / DOM", "CTL-17", "REVIEW",
               "OK" if ok else "KO", " | ".join(f"{k}={v or '?'}" for k, v in vals.items()))

    # ---------- T16 numéro de domiciliation
    n_a2 = dom_ref_compact(_g(d, "ANNEXE_II.numero_domiciliation"))
    n_dom = dom_ref_compact(prow["NUMERO_DOMICILIATION"]) if prow is not None else None
    if not n_a2 or not n_dom:
        ck.add("T16", "N° domiciliation Annexe II = DOM", "AS-04", "REVIEW", "NON_CONTROLABLE",
               f"Annexe II={n_a2 or '?'} | DOM={n_dom or '?'}")
    else:
        ck.add("T16", "N° domiciliation Annexe II = DOM", "AS-04", "REVIEW", "OK" if n_a2 == n_dom else "KO",
               f"Annexe II={n_a2} | DOM={n_dom}")

    # ---------- T06 identité
    ref_nom = prow["NOM_TRAVAILLEUR"] if prow is not None else _g(d, "ANNEXE_II.nom_prenom")
    noms = {"OV bénéficiaire": _g(d, "OV.beneficiaire_nom"), "Annexe I": _g(d, "ANNEXE_I.nom_prenom"),
            "Annexe II": _g(d, "ANNEXE_II.nom_prenom"), "Bulletin": _g(d, "BULLETIN.nom_prenom")}
    sims = {k: name_similarity(ref_nom, v) for k, v in noms.items()}
    faibles = [f"{k} ({v:.2f})" for k, v in sims.items() if v is not None and v < s.seuil_similarite_nom]
    if not ref_nom:
        ck.add("T06", "Identité travailleur concordante", "REG-01", "REVIEW", "NON_CONTROLABLE", "Nom de référence absent")
    else:
        ck.add("T06", "Identité travailleur concordante", "REG-01", "REVIEW", "KO" if faibles else "OK",
               f"Réf. {'DOM/CTS' if prow is not None else 'Annexe II'} : {ref_nom}"
               + (" | écarts : " + ", ".join(faibles) if faibles else ""))

    # ---------- T08 net bulletin = salaire Annexe II
    net = parse_amount(_g(d, "BULLETIN.net_a_payer"))
    sal_a2 = parse_amount(_g(d, "ANNEXE_II.salaire_mensuel"))
    if net is None or sal_a2 is None:
        ck.add("T08", "Net bulletin = salaire Annexe II", "CTL-12", "REVIEW", "NON_CONTROLABLE",
               f"bulletin={net} | annexe II={sal_a2}")
    else:
        ck.add("T08", "Net bulletin = salaire Annexe II", "CTL-12", "REVIEW",
               "OK" if abs(net - sal_a2) <= tol else "KO", f"bulletin={net:,.2f} | annexe II={sal_a2:,.2f}")

    # ---------- Plafonds REG-05 / CTL-15
    caps: dict[str, float] = {}
    cap_a2 = parse_amount(_g(d, "ANNEXE_II.part_transferable"))
    ck.cmp_cap("T09", "OV ≤ part transférable Annexe II", "REG-05 / CTL-11", montant, cap_a2, tol,
               "Part transférable Annexe II non lue")
    if cap_a2 is not None:
        caps["Annexe II"] = cap_a2

    assiette = net if net is not None else sal_a2
    cap95 = round(assiette * s.plafond_pct_net, 2) if assiette is not None else None
    ck.cmp_cap("T10", f"OV ≤ {s.plafond_pct_net:.0%} du net perçu", "REG-05 (assiette à confirmer, Q-01)",
               montant, cap95, tol, "Net non lu (bulletin et Annexe II)")
    if cap95 is not None:
        caps[f"{s.plafond_pct_net:.0%} net"] = cap95

    deja_periode = 0.0
    cap_plan = None
    if prow is not None:
        if not reg_ok.empty:
            deja_periode = float(reg_ok.loc[reg_ok["PERIODE_ID"] == prow["PERIODE_ID"], "_MONTANT"].sum())
        cap_plan = round(float(prow["MONTANT_MAX_THEORIQUE"]) - deja_periode, 2)
    ck.cmp_cap("T11", "OV ≤ part DOM de la période (CTS × prorata − déjà transféré)", "REG-04 / REG-05",
               montant, cap_plan, tol, "Période non rattachée au Planning", "BLOQUANT")
    if cap_plan is not None:
        caps["DOM période"] = cap_plan

    nom_ref = ref_nom or _g(d, "OV.beneficiaire_nom")
    compte_ref = c_dom or c_ov or c_a2
    r_atf, how = _match_ref(atf, mois, compte_ref, nom_ref, s.seuil_similarite_nom)
    if atf is None or atf.empty:
        ck.add("T12", "OV ≤ montant transférable ATF", "REG-05 / CTL-13", "INFO", "NON_CONTROLABLE", "Référentiel ATF non chargé")
    elif r_atf is None:
        ck.add("T12", "OV ≤ montant transférable ATF", "REG-05 / CTL-13", "BLOQUANT", "KO",
               f"Travailleur absent de l'ATF {mois or ''}")
    else:
        cap_atf = parse_amount(r_atf.get("MONTANT_TRANSFERABLE"))
        ck.cmp_cap("T12", "OV ≤ montant transférable ATF", "REG-05 / CTL-13", montant, cap_atf, tol,
                   "Montant ATF vide")
        ck.rows[-1]["DETAIL"] += f" | match {how}"
        if cap_atf is not None:
            caps["ATF"] = cap_atf

    r_aut, how = _match_ref(aut, mois, compte_ref, nom_ref, s.seuil_similarite_nom)
    if aut is None or aut.empty:
        ck.add("T13", "Autorisation ministérielle : plafond et validité", "REG-05 / REG-07 / CTL-14", "INFO",
               "NON_CONTROLABLE", "Référentiel autorisations non chargé")
    elif r_aut is None:
        ck.add("T13", "Autorisation ministérielle : plafond et validité", "REG-05 / CTL-14", "BLOQUANT", "KO",
               f"Travailleur absent des autorisations {mois or ''}")
    else:
        cap_aut = parse_amount(r_aut.get("MONTANT_AUTORISE"))
        ck.cmp_cap("T13", "OV ≤ montant autorisé", "REG-05 / CTL-14", montant, cap_aut, tol, "Montant autorisé vide")
        ck.rows[-1]["DETAIL"] += f" | match {how}"
        if cap_aut is not None:
            caps["Autorisation"] = cap_aut
        lim = parse_date(r_aut.get("DATE_LIMITE"))
        dval = parse_date(r_aut.get("DATE_VALIDATION"))
        if lim is None and dval is not None:
            lim = dval + timedelta(days=s.autorisation_validite_jours)
        dref = parse_date(_g(d, "OV.date_demande")) or today
        if lim is None:
            ck.add("T13b", "Autorisation non échue", "REG-07 (point de départ à confirmer, Q-03)", "REVIEW",
                   "NON_CONTROLABLE", "Ni DATE_LIMITE ni DATE_VALIDATION")
        else:
            ck.add("T13b", "Autorisation non échue", "REG-07 (point de départ à confirmer, Q-03)", "BLOQUANT",
                   "OK" if dref <= lim else "KO", f"date réf. {dref:%d/%m/%Y} / limite {lim:%d/%m/%Y}")

    # ---------- T14 doublon / T15 cumul DOM
    if prow is not None and not reg_ok.empty:
        dup = reg_ok[(reg_ok["PERIODE_ID"] == prow["PERIODE_ID"]) & (reg_ok["FICHIER"] != fichier)]
        ck.add("T14", "Pas de TL déjà validé sur la période", "AS-06 / CTL-19", "REVIEW" if not dup.empty else "BLOQUANT",
               "KO" if not dup.empty else "OK",
               ("Déjà validé : " + ", ".join(dup["FICHIER"])) + f" ({deja_periode:,.2f})" if not dup.empty else "Aucun")
    plafond_dom = cumul_avant = solde_dom = None
    if prow is not None:
        plafond_dom = round(float(planning.loc[planning["DOM_ID"] == prow["DOM_ID"], "MONTANT_MAX_THEORIQUE"].sum()), 2)
        cumul_avant = float(reg_ok.loc[(reg_ok["DOM_ID"] == prow["DOM_ID"]) & (reg_ok["FICHIER"] != fichier),
                                       "_MONTANT"].sum()) if not reg_ok.empty else 0.0
        solde_dom = round(plafond_dom - cumul_avant - (montant or 0), 2)
        ck.add("T15", "Cumul des prélèvements ≤ montant domicilié", "REG-08 / CTL-19 (Q-02)", "BLOQUANT",
               "OK" if solde_dom >= -tol else "KO",
               f"plafond DOM {plafond_dom:,.2f} − cumul {cumul_avant:,.2f} − OV {montant or 0:,.2f} = {solde_dom:,.2f}")

    # ---------- synthèse
    ko_b = [r for r in ck.rows if r["SEVERITE"] == "BLOQUANT" and r["RESULTAT"] == "KO"]
    ko_r = [r for r in ck.rows if r["SEVERITE"] == "REVIEW" and r["RESULTAT"] in ("KO", "NON_CONTROLABLE")]
    statut = "NON_CONFORME" if ko_b else ("A_REVOIR" if ko_r else "CONFORME")
    plafond = min(caps.values()) if caps else None
    synth = {
        "FICHIER": fichier, "AUDIT_SOURCE": d.get("AUDIT_SOURCE"), "STATUT_CONTROLE": statut,
        "NB_BLOQUANT": len(ko_b), "NB_REVIEW": len(ko_r),
        "MOTIFS": " | ".join(f"{r['CODE']} {r['CONTROLE']}" for r in ko_b + ko_r),
        "NOM": nom_ref, "SIEGE_RACINE": siege, "COMPTE_LOCAL": compte_ref or None,
        "PERIODE_TL": prow["PERIODE_TL"] if prow is not None else periode_label(mois, part),
        "PERIODE_ID": prow["PERIODE_ID"] if prow is not None else None,
        "DOM_ID": prow["DOM_ID"] if prow is not None else None,
        "NUMERO_DOMICILIATION": prow["NUMERO_DOMICILIATION"] if prow is not None else _g(d, "ANNEXE_II.numero_domiciliation"),
        "MONTANT_OV": montant, "DEVISE": devise,
        **{f"PLAFOND_{k.upper().replace(' ', '_').replace('%', 'PCT')}": v for k, v in caps.items()},
        "PLAFOND_RETENU": plafond, "PLAFOND_LIMITANT": min(caps, key=caps.get) if caps else None,
        "MARGE": round(plafond - montant, 2) if (plafond is not None and montant is not None) else None,
        "PROVISION_ATLAS": round(montant + s.provision_majoration_dzd, 2) if montant is not None else None,
        "PLAFOND_DOM": plafond_dom, "CUMUL_DOM_AVANT": cumul_avant, "SOLDE_DOM_APRES": solde_dom,
        "BENEFICIAIRE": _g(d, "OV.beneficiaire_nom"), "BENEFICIAIRE_COMPTE": _g(d, "OV.beneficiaire_compte"),
        "SWIFT": _g(d, "OV.swift"), "BANQUE": _g(d, "OV.banque_nom"), "DATE_DEMANDE": _g(d, "OV.date_demande"),
    }
    return synth, ck.rows


def run_controls(audit: pd.DataFrame, planning: pd.DataFrame, registre: pd.DataFrame,
                 atf: pd.DataFrame, aut: pd.DataFrame, s, today: date | None = None):
    reg_ok = _registre_valide(registre)
    synth, checks = [], []
    for _, r in audit.iterrows():
        a, b = control_dossier(r.to_dict(), planning, reg_ok, atf, aut, s, today)
        synth.append(a)
        checks.extend(b)
    sy = pd.DataFrame(synth)
    ch = pd.DataFrame(checks)
    # Doublons à l'intérieur du lot
    if not sy.empty:
        dup = sy[sy["PERIODE_ID"].notna() & sy.duplicated("PERIODE_ID", keep=False)]
        for pid, grp in dup.groupby("PERIODE_ID"):
            for f in grp["FICHIER"]:
                autres = ", ".join(x for x in grp["FICHIER"] if x != f)
                ch = pd.concat([ch, pd.DataFrame([{"FICHIER": f, "CODE": "T14b", "CONTROLE": "Doublon dans le lot",
                                                   "REFERENCE": "CTL-19", "SEVERITE": "BLOQUANT", "RESULTAT": "KO",
                                                   "DETAIL": f"Même période que {autres}"}])], ignore_index=True)
                i = sy.index[sy["FICHIER"] == f][0]
                sy.at[i, "STATUT_CONTROLE"] = "NON_CONFORME"
                sy.at[i, "NB_BLOQUANT"] += 1
                sy.at[i, "MOTIFS"] = (sy.at[i, "MOTIFS"] + " | " if sy.at[i, "MOTIFS"] else "") + "T14b Doublon dans le lot"
    return sy, ch


# ------------------------------------------------------------------ décisions / registre
DECISION_VALUES = ["", "VALIDE", "REJETE", "EN_ATTENTE"]


def load_decisions(path: Path) -> pd.DataFrame:
    cols = ["FICHIER", "AUDIT_SOURCE", "DECISION", "COMMENTAIRE", "USER", "TS"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").reindex(columns=cols)
    return df.drop_duplicates("FICHIER", keep="last")


def save_decisions(path: Path, edited: pd.DataFrame, user: str) -> int:
    old = load_decisions(path)
    old_map = {r.FICHIER: (r.DECISION or "", r.COMMENTAIRE or "") for r in old.fillna("").itertuples()}
    new_rows = []
    for _, r in edited.iterrows():
        dec, com = (r.get("DECISION") or "").strip(), (r.get("COMMENTAIRE") or "").strip()
        if old_map.get(r["FICHIER"], ("", "")) != (dec, com) and (dec or com or r["FICHIER"] in old_map):
            new_rows.append({"FICHIER": r["FICHIER"], "AUDIT_SOURCE": r.get("AUDIT_SOURCE"), "DECISION": dec,
                             "COMMENTAIRE": com, "USER": user, "TS": datetime.now().isoformat(timespec="seconds")})
    if new_rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        hist = pd.read_csv(path, dtype=str, encoding="utf-8-sig") if path.exists() else pd.DataFrame()
        pd.concat([hist, pd.DataFrame(new_rows)], ignore_index=True).to_csv(path, index=False, encoding="utf-8-sig")
    return len(new_rows)


def check_decisions(edited: pd.DataFrame) -> list[str]:
    errs = []
    for _, r in edited.iterrows():
        dec = (r.get("DECISION") or "").strip()
        if dec == "VALIDE" and r.get("STATUT_CONTROLE") == "NON_CONFORME" and not (r.get("COMMENTAIRE") or "").strip():
            errs.append(f"{r['FICHIER']} : validation d'un dossier NON_CONFORME sans justification")
        if dec == "VALIDE" and not r.get("PERIODE_ID"):
            errs.append(f"{r['FICHIER']} : impossible de valider un TL non rattaché au Planning")
        if dec == "REJETE" and not (r.get("COMMENTAIRE") or "").strip():
            errs.append(f"{r['FICHIER']} : rejet sans motif")
    return errs


def register(path: Path, synth: pd.DataFrame, decisions: pd.DataFrame, user: str) -> int:
    """Ajoute au registre les TL validés (idempotent par TL_ID)."""
    reg = load_registre(path)
    known = set(reg["TL_ID"].dropna())
    dec = decisions.set_index("FICHIER") if not decisions.empty else pd.DataFrame()
    rows = []
    for _, r in synth.iterrows():
        if r["FICHIER"] not in dec.index or dec.loc[r["FICHIER"], "DECISION"] != "VALIDE":
            continue
        tid = tl_id(r["FICHIER"], r.get("PERIODE_ID"))
        if tid in known:
            continue
        rows.append({"TL_ID": tid, "FICHIER": r["FICHIER"], "DOM_ID": r.get("DOM_ID"),
                     "PERIODE_ID": r.get("PERIODE_ID"), "PERIODE_TL": r.get("PERIODE_TL"),
                     "SIEGE_RACINE": r.get("SIEGE_RACINE"), "NOM": r.get("NOM"),
                     "NUMERO_DOMICILIATION": r.get("NUMERO_DOMICILIATION"), "MONTANT": r.get("MONTANT_OV"),
                     "DEVISE": r.get("DEVISE"), "PROVISION_ATLAS": r.get("PROVISION_ATLAS"),
                     "STATUT_CONTROLE": r.get("STATUT_CONTROLE"), "DECISION": "VALIDE",
                     "COMMENTAIRE": dec.loc[r["FICHIER"], "COMMENTAIRE"], "VALIDE_PAR": user,
                     "DATE_VALIDATION": datetime.now().isoformat(timespec="seconds"),
                     "STATUT_EXECUTION": "A_EXECUTER"})
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.concat([reg, pd.DataFrame(rows)], ignore_index=True).reindex(columns=REGISTRE_COLUMNS) \
            .to_csv(path, index=False, encoding="utf-8-sig")
    return len(rows)


def consumption(planning: pd.DataFrame, registre: pd.DataFrame, today: date | None = None,
                tol: float = 1.0) -> pd.DataFrame:
    """Planning enrichi : montant transféré, solde, statut par période (base AS-07)."""
    today = today or date.today()
    if planning is None or planning.empty:
        return pd.DataFrame()
    p = planning.copy()
    reg = _registre_valide(registre)
    sums = reg.groupby("PERIODE_ID")["_MONTANT"].sum() if not reg.empty else pd.Series(dtype=float)
    last = reg.groupby("PERIODE_ID")["DATE_VALIDATION"].max() if not reg.empty else pd.Series(dtype=str)
    p["MONTANT_TRANSFERE"] = p["PERIODE_ID"].map(sums).fillna(0.0).round(2)
    p["SOLDE_RESTANT"] = (p["MONTANT_MAX_THEORIQUE"].astype(float) - p["MONTANT_TRANSFERE"]).round(2)
    p["DATE_EXECUTION_TL"] = p["PERIODE_ID"].map(last)

    def statut(r):
        if r["MONTANT_TRANSFERE"] > 0 and r["SOLDE_RESTANT"] <= tol:
            return "TRANSFERE"
        if r["MONTANT_TRANSFERE"] > 0:
            return "PARTIEL"
        fin = parse_date(r["DATE_FIN_SEGMENT"])
        return "NON_TRANSFERE" if fin and fin < today else "A_VENIR"

    p["STATUT_PERIODE"] = p.apply(statut, axis=1)
    return p
