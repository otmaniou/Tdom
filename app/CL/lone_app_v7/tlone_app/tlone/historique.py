"""Historique des TL : système comptable (Atlas) × CarthagoTrade, blocages et soldes — régularisation de la base.

Fichiers (exports bruts, nom horodaté ; le plus récent de chaque type est lu) :
  * Historique_mouvement_altas-AAAA-MM-JJThhmmss.xlsx  (mouvements comptables Atlas)
      id_tiers, Date_operation_Atlas, lib_complementaire_mvt, Reference_denotage, Reference_client,
      Date_Valeur_comptable, Montant_mvt_comptable
      -> la référence TL est écrite en texte libre dans lib_complementaire_mvt (« TL » + chiffres).
  * Transfert libre -AAAA-MM-JJThhmmss.xls             (CarthagoTrade)
      Référence (TL…), Code client, Nom, Montant, Statut, Objet du transfert (période), …
      ATTENTION export Carthago : « Nom2 » = nationalité, « Nom3 » = pays de destination des fonds.
  * Blocage-AAAA-MM-JJThhmmss.xlsx                     (fonds bloqués)
      SIEGE, RACINE, ORDINAL, DEVISE, REFERENCE DENOTAGE DU MOUVEMENT, MT BLOCAGE DEV CPT,
      DATE DEBUT BLOCAGE (AAAAMMJJ), DATE LIMITE BLOCAGE (AAAAMMJJ)
  * comptes_solde-AAAA-MM-JJThhmmss.xlsx               (soldes)
      compte_local (ex. 0731010920500191DZD), Solde_Compta, Solde_Dispo

Jointures : Atlas.référence TL extraite = Trade.Référence ; Atlas.Reference_denotage ≈ Blocage.REFERENCE DENOTAGE
(même client) ; client = siège + racine (07310 + 6 chiffres).
Contrôle majeur : une référence TL débitée plusieurs fois dans Atlas = montant transféré deux fois (risque élevé).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .common import digits, is_blank, parse_amount, parse_date, siege_racine

TL_RE = re.compile(r"\bTL\s*[-_]?\s*(\d{8,9})(?!\d)", re.I)
MOIS = {"JANVIER": 1, "JANV": 1, "JAN": 1, "FEVRIER": 2, "FEVR": 2, "FEV": 2, "MARS": 3, "MAR": 3,
        "AVRIL": 4, "AVR": 4, "MAI": 5, "JUIN": 6, "JUILLET": 7, "JUIL": 7, "AOUT": 8, "AOU": 8,
        "SEPTEMBRE": 9, "SEPT": 9, "SEP": 9, "OCTOBRE": 10, "OCT": 10, "NOVEMBRE": 11, "NOV": 11,
        "DECEMBRE": 12, "DEC": 12}
PATTERNS = {   # type de fichier -> préfixe (comparaison sans casse, espaces / tirets / _ ignorés)
    "atlas": ("historiquemouvementaltas", "historiquemouvementatlas"),
    "trade": ("transfertlibre",),
    "blocage": ("blocage",),
    "soldes": ("comptessolde", "comptesolde"),
}
LABEL = {"atlas": "Historique des mouvements Atlas", "trade": "Transferts libres CarthagoTrade",
         "blocage": "Blocages", "soldes": "Soldes des comptes"}


def _key(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _up(s) -> str:
    s = "" if is_blank(s) else str(s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(s.upper().split())


# ------------------------------------------------------------------ fichiers
def kind_of(name: str) -> str | None:
    k = _key(Path(name).stem)
    for kind, prefixes in PATTERNS.items():
        if any(k.startswith(p.upper()) for p in prefixes):
            return kind
    return None


def latest(folder: Path) -> dict[str, Path]:
    """Fichier le plus récent de chaque type (par horodatage du nom, sinon date de modification)."""
    out: dict[str, tuple] = {}
    if not folder.exists():
        return {}
    for p in folder.iterdir():
        if not p.is_file() or p.suffix.lower() not in (".xls", ".xlsx", ".csv"):
            continue
        kind = kind_of(p.name)
        if not kind:
            continue
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})T(\d{2})-?(\d{2})-?(\d{2})", p.name)
        stamp = "".join(m.groups()) if m else datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y%m%d%H%M%S")
        if kind not in out or stamp > out[kind][0]:
            out[kind] = (stamp, p)
    return {k: v[1] for k, v in out.items()}


def read_table(path: Path) -> pd.DataFrame:
    """xlsx, xls (binaire ou HTML déguisé, fréquent dans les exports web) ou csv ; tout en texte."""
    suf = path.suffix.lower()
    if suf == ".csv":
        return pd.read_csv(path, dtype=str, sep=None, engine="python", encoding="utf-8-sig")
    if suf == ".xls":
        head = path.read_bytes()[:512].lstrip().lower()
        if head.startswith((b"<", b"\xef\xbb\xbf<")):
            return pd.read_html(path, flavor=None)[0].astype(str).replace({"nan": None})
        try:
            return pd.read_excel(path, dtype=str, engine="xlrd")
        except ImportError as exc:
            raise ImportError("Lecture .xls : paquet « xlrd » absent de l'image (à ajouter à la révision "
                              "d'environnement) — ou enregistrer le fichier en .xlsx") from exc
    return pd.read_excel(path, dtype=str)


def _col(df: pd.DataFrame, *names) -> str | None:
    keys = {_key(c): c for c in df.columns}
    for n in names:
        if _key(n) in keys:
            return keys[_key(n)]
    return None


def _require(df, mapping: dict, label: str) -> dict:
    found = {k: _col(df, *v) for k, v in mapping.items()}
    miss = [mapping[k][0] for k, c in found.items() if c is None]
    if miss:
        raise ValueError(f"{label} : colonnes absentes : {', '.join(miss)} (en-têtes lus : {', '.join(map(str, df.columns))})")
    return found


# ------------------------------------------------------------------ période (objet du transfert / dénotage)
def parse_periode(v) -> dict:
    """« 052026 », « 052026P1 », « 62026 », « 20257P2 », « Juin 26 », « COMPLEMENT JANV 2026 »…
    Règle unique de TL-One : voir tlone.periode.lire."""
    from .periode import lire
    return lire(v)


# ------------------------------------------------------------------ lecture des 4 fichiers
def load_trade(path: Path) -> pd.DataFrame:
    df = read_table(path)
    c = _require(df, {"ref": ("Référence",), "client": ("Code client",), "nom": ("Nom",), "montant": ("Montant",),
                      "statut": ("Statut",), "objet": ("Objet du transfert",)}, "CarthagoTrade")
    opt = {k: _col(df, *v) for k, v in {
        "nationalite": ("Nom2",), "pays": ("Nom3",), "devise_cible": ("Devise cible",), "date_valeur": ("Date valeur",),
        "date_demande": ("Date demande",), "domiciliation": ("N° domiciliation", "N domiciliation"),
        "predom": ("Référence prédom",), "compte": ("Compte à débiter (Siège+ Racine+ Ordinal)", "Compte à débiter"),
        "beneficiaire": ("Nom/Raison sociale bénéficiaire",), "banque": ("Nom banque bénéficiaire",),
        "adresse": ("Adresse",), "adresse_benef": ("Adresse bénéficiaire",),
        "compte_benef": ("Compte bénéficiaire",), "swift": ("Code Swift",), "agence": ("Agence",),
        "type": ("Type de transfert",)}.items()}
    rows = []
    for _, r in df.iterrows():
        ref = (TL_RE.search(str(r[c["ref"]] or "")) or [None, None])[1]
        per = parse_periode(r[c["objet"]])
        cl = siege_racine(r[c["client"]]) or digits(r[c["client"]])
        cpt = r[opt["compte"]] if opt["compte"] else None
        rows.append({
            "REF_TL": f"TL{ref}" if ref else None, "REFERENCE_BRUTE": r[c["ref"]], "CLIENT": cl, "NOM": r[c["nom"]],
            "MONTANT_TRADE": parse_amount(r[c["montant"]]), "STATUT_TRADE": r[c["statut"]],
            "OBJET": r[c["objet"]], "PERIODE": per["periode"], "MOIS": per["mois"], "TRANCHE": per["tranche"],
            "JOURS": per["jours"], "COMPLEMENT": per["complement"], "STATUT_PERIODE": per["statut"],
            "REGLE_PERIODE": per["regle"],
            "NATIONALITE": r[opt["nationalite"]] if opt["nationalite"] else None,
            "PAYS_DESTINATION": r[opt["pays"]] if opt["pays"] else None,
            **{k.upper(): (r[col] if col else None) for k, col in opt.items()
               if k not in ("nationalite", "pays", "compte", "date_valeur", "date_demande")},
            "DATE_VALEUR_TRADE": parse_date(r[opt["date_valeur"]]) if opt["date_valeur"] else None,
            "DATE_DEMANDE_TRADE": parse_date(r[opt["date_demande"]]) if opt["date_demande"] else None,
            "COMPTE_A_DEBITER": cpt,
            "COMPTE_COHERENT": (None if is_blank(cpt) or not siege_racine(cpt) else siege_racine(cpt) == cl),
        })
    return pd.DataFrame(rows)


def load_atlas(path: Path) -> pd.DataFrame:
    df = read_table(path)
    c = _require(df, {"tiers": ("id_tiers",), "date_op": ("Date_operation_Atlas",), "lib": ("lib_complementaire_mvt",),
                      "denot": ("Reference_denotage",), "refcli": ("Reference_client",),
                      "date_val": ("Date_Valeur_comptable",), "montant": ("Montant_mvt_comptable",)}, "Atlas")
    rows = []
    for i, r in df.iterrows():
        refs = list(dict.fromkeys(f"TL{x}" for x in TL_RE.findall(str(r[c["lib"]] or ""))))
        rows.append({
            "LIGNE_ATLAS": i + 2, "ID_TIERS": r[c["tiers"]], "CLIENT": siege_racine(r[c["tiers"]]) or digits(r[c["tiers"]]),
            "DATE_OPERATION": parse_date(r[c["date_op"]]), "LIBELLE": r[c["lib"]],
            "REF_TL": refs[0] if refs else None, "REFS_TL_LIBELLE": " | ".join(refs),
            "REFERENCE_DENOTAGE": r[c["denot"]], "REFERENCE_CLIENT": r[c["refcli"]],
            "DATE_VALEUR": parse_date(r[c["date_val"]]), "MONTANT_ATLAS": parse_amount(r[c["montant"]]),
        })
    return pd.DataFrame(rows)


def _ymd(v):
    d = digits(v)
    if len(d) == 8:
        try:
            return date(int(d[:4]), int(d[4:6]), int(d[6:]))
        except ValueError:
            return None
    return parse_date(v)


def load_blocage(path: Path) -> pd.DataFrame:
    df = read_table(path)
    c = _require(df, {"siege": ("SIEGE",), "racine": ("RACINE",), "ordinal": ("ORDINAL",), "devise": ("DEVISE",),
                      "denot": ("REFERENCE DENOTAGE DU MOUVEMENT",), "mt": ("MT BLOCAGE DEV CPT",),
                      "debut": ("DATE DEBUT BLOCAGE",), "fin": ("DATE LIMITE BLOCAGE",)}, "Blocages")
    rows = []
    for _, r in df.iterrows():
        sg, rc = digits(r[c["siege"]]).zfill(5), digits(r[c["racine"]]).zfill(6)
        per = parse_periode(r[c["denot"]])
        rows.append({"CLIENT": sg + rc, "ORDINAL": digits(r[c["ordinal"]]).zfill(3), "DEVISE": r[c["devise"]],
                     "REFERENCE_DENOTAGE": r[c["denot"]], "PERIODE": per["periode"], "MOIS": per["mois"],
                     "STATUT_PERIODE": per["statut"],
                     "MONTANT_BLOCAGE": abs(parse_amount(r[c["mt"]]) or 0) or None,
                     "DATE_DEBUT": _ymd(r[c["debut"]]), "DATE_LIMITE": _ymd(r[c["fin"]])})
    return pd.DataFrame(rows)


def load_soldes(path: Path) -> pd.DataFrame:
    df = read_table(path)
    c = _require(df, {"cpt": ("compte_local",), "compta": ("Solde_Compta",), "dispo": ("Solde_Dispo",)}, "Soldes")
    rows = []
    for _, r in df.iterrows():
        d = digits(r[c["cpt"]])
        rows.append({"COMPTE_LOCAL": r[c["cpt"]], "CLIENT": d[:11] if len(d) >= 11 else None,
                     "ORDINAL": d[11:14] if len(d) >= 14 else None,
                     "SOLDE_COMPTA": parse_amount(r[c["compta"]]), "SOLDE_DISPO": parse_amount(r[c["dispo"]])})
    return pd.DataFrame(rows)


def norm_denotage(v) -> str:
    p = parse_periode(v)
    return p["periode"] or _key(v)


# ------------------------------------------------------------------ rapprochement et anomalies
EXECUTE = {"EXECUTE"}


def _statut_key(v) -> str:
    return _key(v)


def reconcile(atlas: pd.DataFrame, trade: pd.DataFrame, blocage: pd.DataFrame | None = None,
              tol: float = 1.0) -> dict[str, pd.DataFrame]:
    """Une ligne par mouvement Atlas + TL Trade sans mouvement ; anomalies classées par gravité."""
    an: list[dict] = []

    def add(grav, code, libelle, ref=None, client=None, periode=None, detail=""):
        an.append({"GRAVITE": grav, "CODE": code, "ANOMALIE": libelle, "REF_TL": ref, "CLIENT": client,
                   "PERIODE": periode, "DETAIL": detail})

    atlas = atlas.copy() if atlas is not None else pd.DataFrame(columns=["REF_TL"])
    trade = trade.copy() if trade is not None else pd.DataFrame(columns=["REF_TL"])
    # H01 — référence TL débitée plusieurs fois dans Atlas (montant transféré deux fois)
    if not atlas.empty:
        dup = atlas[atlas["REF_TL"].notna() & atlas["REF_TL"].duplicated(keep=False)].groupby("REF_TL")
        for ref, g in dup:
            if len(g) > 1:
                add("CRITIQUE", "H01", "Référence TL débitée plusieurs fois dans Atlas (double transfert)", ref,
                    g["CLIENT"].iloc[0], None, f"{len(g)} mouvements, lignes {', '.join(map(str, g['LIGNE_ATLAS']))} ; "
                    f"total {g['MONTANT_ATLAS'].abs().sum():,.2f}")
        for _, r in atlas[atlas["REF_TL"].isna()].iterrows():
            add("A_VERIFIER", "H02", "Mouvement Atlas sans référence TL dans le libellé", None, r["CLIENT"], None,
                f"ligne {r['LIGNE_ATLAS']} : « {r['LIBELLE']} »")
        for _, r in atlas[atlas["REFS_TL_LIBELLE"].str.contains(r"\|", na=False)].iterrows():
            add("A_VERIFIER", "H03", "Plusieurs références TL dans un même libellé", r["REF_TL"], r["CLIENT"], None,
                f"ligne {r['LIGNE_ATLAS']} : {r['REFS_TL_LIBELLE']}")
    if not trade.empty:
        for ref, g in trade[trade["REF_TL"].notna() & trade["REF_TL"].duplicated(keep=False)].groupby("REF_TL"):
            if len(g) > 1:
                add("ELEVEE", "H04", "Référence TL en double dans CarthagoTrade", ref, g["CLIENT"].iloc[0])
    tr1 = trade.drop_duplicates("REF_TL") if not trade.empty else trade
    m = atlas.merge(tr1, on="REF_TL", how="left", suffixes=("", "_TRADE"), indicator=True) if not atlas.empty \
        else pd.DataFrame()
    if not m.empty:
        for r in m.to_dict("records"):
            if pd.isna(r.get("REF_TL")):
                continue
            if r["_merge"] == "left_only":
                add("ELEVEE", "H05", "Débit Atlas sans TL correspondant dans CarthagoTrade", r["REF_TL"], r["CLIENT"])
                continue
            if r.get("CLIENT_TRADE") and r.get("CLIENT") and r["CLIENT_TRADE"] != r["CLIENT"]:
                add("ELEVEE", "H06", "Client différent Atlas / CarthagoTrade", r["REF_TL"], r["CLIENT"], r.get("PERIODE"),
                    f"Atlas {r['CLIENT']} / Trade {r['CLIENT_TRADE']}")
            ma, mt = r.get("MONTANT_ATLAS"), r.get("MONTANT_TRADE")
            if ma is not None and mt is not None and not pd.isna(ma) and not pd.isna(mt) and abs(abs(ma) - mt) > tol:
                add("ELEVEE", "H07", "Montant différent Atlas / CarthagoTrade", r["REF_TL"], r["CLIENT"], r.get("PERIODE"),
                    f"Atlas {abs(ma):,.2f} / Trade {mt:,.2f}")
            if _statut_key(r.get("STATUT_TRADE")) == "REJETE":
                add("CRITIQUE", "H08", "TL rejeté dans CarthagoTrade mais débité dans Atlas", r["REF_TL"], r["CLIENT"],
                    r.get("PERIODE"))
    decale = colonne_compte_decalee(trade)
    if decale:
        add("ELEVEE", "H15", "Export CarthagoTrade : colonne « Compte à débiter » décalée d'une ligne", None, None, None,
            f"{decale} ligne(s) portent le compte du dossier précédent — contrôle compte / client suspendu ; "
            "refaire l'extraction Carthago")
    if not tr1.empty:
        vus = set(atlas["REF_TL"].dropna()) if not atlas.empty else set()
        for r in tr1.to_dict("records"):
            if _statut_key(r["STATUT_TRADE"]) in EXECUTE and r["REF_TL"] not in vus and not atlas.empty:
                add("ELEVEE", "H09", "TL « Exécuté » dans CarthagoTrade sans débit Atlas (statut ANOMALIE : ni exécuté, ni en cours)", r["REF_TL"], r["CLIENT"],
                    r["PERIODE"])
            if r["STATUT_PERIODE"] != "OK" and _statut_key(r["STATUT_TRADE"]) != "REJETE":
                add("A_VERIFIER", "H10", "Période illisible ou incomplète dans l'objet du transfert", r["REF_TL"],
                    r["CLIENT"], r["PERIODE"], f"« {r['OBJET']} » : {r['REGLE_PERIODE'] or r['STATUT_PERIODE']}")
            if r.get("COMPTE_COHERENT") is False and not decale:
                add("A_VERIFIER", "H11", "Compte à débiter d'un autre client que le code client", r["REF_TL"],
                    r["CLIENT"], r["PERIODE"], f"compte {r['COMPTE_A_DEBITER']}")
    # H12 — même période transférée deux fois. Seul un débit Atlas fait foi d'exécution ; sans fichier Atlas,
    # on se rabat sur les statuts CarthagoTrade (Exécuté / En cours d'exécution).
    if not atlas.empty:
        eff = tr1[tr1["REF_TL"].isin(set(atlas["REF_TL"].dropna()))] if not tr1.empty else tr1
    else:
        eff = tr1[tr1["STATUT_TRADE"].map(_statut_key).isin(EXECUTE | {"ENCOURSDEXECUTION"})] if not tr1.empty else tr1
    if not eff.empty:
        e2 = eff[eff["MOIS"].notna()]
        e2 = e2[e2.duplicated(["CLIENT", "MOIS"], keep=False)]
        for (cl, mois), g in e2.groupby(["CLIENT", "MOIS"]):
            if len(g) < 2:
                continue
            tr = list(g["TRANCHE"].fillna("COMPLET"))
            conflit = len(tr) != len(set(tr)) or ("COMPLET" in tr and len(tr) > 1)
            if conflit and "COMPLEMENT" in g and g["COMPLEMENT"].fillna("").astype(str).str.len().gt(0).any():
                add("A_VERIFIER", "H12b", "Même mois transféré plusieurs fois avec un complément", ", ".join(g["REF_TL"].astype(str)),
                    cl, mois, "cumul à comparer à la part de la période (Planning) : "
                    + " | ".join(f"{a} {c:,.2f}" for a, c in zip(g["REF_TL"], g["MONTANT_TRADE"].fillna(0))))
            elif conflit:
                add("CRITIQUE", "H12", "Même mois transféré plusieurs fois", ", ".join(g["REF_TL"].astype(str)), cl, mois,
                    " | ".join(f"{a} {b if isinstance(b, str) and b else 'mois complet'} ({c})" for a, b, c in
                               zip(g["REF_TL"], g["TRANCHE"], g["STATUT_TRADE"])))
    # H13 / H14 — blocage du dénotage Atlas
    if blocage is not None and not blocage.empty and not atlas.empty:
        bl = blocage.assign(_K=blocage["REFERENCE_DENOTAGE"].map(norm_denotage))
        keys = set(zip(bl["CLIENT"], bl["_K"]))
        # le fichier des blocages ne couvre que sa période : pas d'alerte pour les débits antérieurs
        debut_bl = bl["DATE_DEBUT"].dropna().min() if "DATE_DEBUT" in bl else None
        per_of = dict(zip(tr1["REF_TL"], tr1["PERIODE"])) if not tr1.empty else {}
        for _, r in atlas[atlas["REF_TL"].notna()].iterrows():
            k = norm_denotage(r["REFERENCE_DENOTAGE"]) if not is_blank(r["REFERENCE_DENOTAGE"]) else None
            if k and (r["CLIENT"], k) not in keys and not (debut_bl and r.get("DATE_OPERATION")
                                                             and r["DATE_OPERATION"] < debut_bl):
                add("A_VERIFIER", "H13", "Dénotage Atlas sans blocage correspondant", r["REF_TL"], r["CLIENT"], k,
                    f"dénotage « {r['REFERENCE_DENOTAGE']} »")
            p = per_of.get(r["REF_TL"])
            if k and p and re.fullmatch(r"\d{4}-\d{2}(P[12])?", k) and k != p:
                add("ELEVEE", "H14", "Période du dénotage ≠ période de l'objet du transfert", r["REF_TL"], r["CLIENT"], p,
                    f"dénotage {k} / objet {p}")
    ordre = {"CRITIQUE": 0, "ELEVEE": 1, "A_VERIFIER": 2}
    anomalies = pd.DataFrame(an, columns=["GRAVITE", "CODE", "ANOMALIE", "REF_TL", "CLIENT", "PERIODE", "DETAIL"])
    anomalies = anomalies.sort_values(["GRAVITE", "CODE"], key=lambda s: s.map(ordre) if s.name == "GRAVITE" else s)
    histo = m.drop(columns=["_merge"]) if not m.empty else pd.DataFrame()
    if not tr1.empty and not atlas.empty:
        sans = tr1[~tr1["REF_TL"].isin(set(atlas["REF_TL"].dropna()))]
        histo = pd.concat([histo, sans.assign(SOURCE="Trade seul")], ignore_index=True)
    elif not tr1.empty:
        histo = tr1.assign(SOURCE="Trade seul")
    return {"historique": histo, "anomalies": anomalies.reset_index(drop=True)}


def colonne_compte_decalee(trade: pd.DataFrame) -> int:
    """Nombre de lignes dont le « Compte à débiter » est celui du client de la ligne précédente (export décalé).
    Retourne 0 si ce motif n'explique pas la majorité des incohérences compte / client."""
    if trade is None or trade.empty or "COMPTE_A_DEBITER" not in trade:
        return 0
    cl = list(trade["CLIENT"])
    cp = [siege_racine(x) for x in trade["COMPTE_A_DEBITER"]]
    bad = [i for i in range(len(cl)) if cp[i] and cp[i] != cl[i]]
    shift = [i for i in bad if i > 0 and cp[i] == cl[i - 1]]
    return len(shift) if bad and len(shift) >= max(2, len(bad) // 2) else 0


def periodes_par_client(trade: pd.DataFrame, atlas: pd.DataFrame | None = None) -> pd.DataFrame:
    """Périodes réellement transférées par client : TL débités dans Atlas (sans fichier Atlas : statut Trade
    « Exécuté »). Base du Planning / registre."""
    if trade is None or trade.empty:
        return pd.DataFrame()
    t = trade.drop_duplicates("REF_TL")
    if atlas is not None and not atlas.empty:
        t = t[t["REF_TL"].isin(set(atlas["REF_TL"].dropna()))]
    else:
        t = t[t["STATUT_TRADE"].map(_statut_key).isin(EXECUTE)]
    return (t[t["PERIODE"].notna()].sort_values(["CLIENT", "PERIODE"])
            [["CLIENT", "NOM", "PERIODE", "REF_TL", "MONTANT_TRADE", "STATUT_TRADE", "OBJET"]].reset_index(drop=True))
