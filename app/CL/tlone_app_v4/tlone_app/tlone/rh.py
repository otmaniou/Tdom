"""Base RH mensuelle de l'employeur (« base_RH_AAAAMM.xlsx »).

L'employeur confirme que tous les documents (DOM, CTS, OV, Annexes, bulletin) sont imprimés depuis ce fichier,
hormis le permis de travail : c'est le référentiel de comparaison. Réglementairement, le TL s'exécute sur la
base de l'OV : la base RH ne remplace jamais l'OV, elle le contrôle (et complète l'adresse du bénéficiaire).

Une ligne par salarié et par PART (PART 1 / PART 2 quand le contrat change dans le mois).
Règle observée : part transférable = 95 % × salaire net × nombre de jours / 30 ; part payable = 5 %.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

from .common import digits, is_blank, name_similarity, parse_amount, parse_date
from .periode import lire

# en-tête normalisé -> colonne canonique
HEADERS = {
    "MATRICULE SAP": "MATRICULE", "MATRICULE KELIO": "MATRICULE_KELIO", "NOM ET PRENOM": "NOM_PRENOM",
    "NOM": "NOM", "PRENOM": "PRENOM", "DATE DE NAISSANCE": "DATE_NAISSANCE", "LIEU DE NAISSANCE": "LIEU_NAISSANCE",
    "NOM DU PERE": "PERE", "NOM DE LA MERE": "MERE", "DATE D ENTREE EN ALGERIE": "DATE_ENTREE",
    "FONCTION": "FONCTION", "QUALIFICATION": "QUALIFICATION", "PERMIT TRAVAIL N": "PERMIS",
    "PERMIS TRAVAIL N": "PERMIS", "DATE DE DELIVRANCE": "PERMIS_DELIVRANCE", "DATE D EMISSION": "PERMIS_DEBUT",
    "FIN DE VALIDITE": "PERMIS_FIN", "DUREE DU PERMIS DE TRAVAIL MOIS": "PERMIS_DUREE_MOIS",
    "DATE D ATTESTATION": "DATE_ATTESTATION", "SALAIRE POSTE": "SALAIRE_POSTE", "RETENUE SS": "RETENUE_SS",
    "IRG": "IRG", "RETENUE MUTUELLE": "RETENUE_MUTUELLE", "SALAIRE NET": "SALAIRE_NET",
    "PART TRANSFERABLE": "PART_TRANSFERABLE", "PART PAYABLE": "PART_PAYABLE",
    "COMPTE BANCAIRE ALGERIE": "RIB", "NOM DE BANQUE ALGERIE": "BANQUE_DZ", "AGENCE DE BANK ALGERIE": "AGENCE",
    "AGENCE DE BANQUE ALGERIE": "AGENCE", "COMPTE DEVISE": "IBAN", "NOM DE BANQUE ETRANGE": "BANQUE_ETR",
    "NOM DE BANQUE ETRANGER": "BANQUE_ETR", "PAYS DE LA BANQUE ETRANGE": "PAYS_BANQUE",
    "PAYS DE LA BANQUE ETRANGER": "PAYS_BANQUE", "NOM DU BENEFICIAIRE": "BENEF_NOM",
    "PRENOM DU BENEFICIAIRE": "BENEF_PRENOM", "DEVISE DU TRANSFERT": "DEVISE", "MOIS DE PAIEMENT": "MOIS_PAIEMENT",
    "SWIFT BIC": "SWIFT", "ADRESSE": "ADRESSE_BENEF", "CONTRAT N": "CONTRAT_N",
    "DATE D ETABLISSEMENT": "DATE_ETABLISSEMENT", "NOMBRE DE JOURS": "NB_JOURS", "PART": "PART",
}
REQUIRED = ["NOM_PRENOM", "RIB", "SALAIRE_NET", "PART_TRANSFERABLE", "MOIS_PAIEMENT"]
PCT = 0.95


def hkey(v) -> str:
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", s)).strip()


def iban_clean(v) -> str:
    return "" if is_blank(v) else re.sub(r"[^A-Z0-9]", "", str(v).upper())


IBAN_LEN = {"TR": 26, "DE": 22, "FR": 27, "IT": 27, "ES": 24, "PT": 25, "GB": 22, "BE": 16, "NL": 18, "CH": 21,
            "AT": 20, "AZ": 28, "EG": 29, "TN": 24, "UA": 29, "PK": 24, "JO": 30, "LB": 28, "SA": 24, "AE": 23}


def iban_ok(v) -> bool | None:
    """Clé ISO 13616 (mod 97 = 1) et longueur du pays pour les IBAN ; None pour un compte non IBAN (ex. Inde)."""
    s = iban_clean(v)
    if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$", s):
        return None
    if s[:2] in IBAN_LEN and len(s) != IBAN_LEN[s[:2]]:
        return False
    n = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(n) % 97 == 1


def swift11(v) -> str:
    s = re.sub(r"[^A-Z0-9]", "", str(v or "").upper())
    return s + "XXX" if len(s) == 8 else s


def swift_ok(v) -> bool:
    return bool(re.match(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$", re.sub(r"[^A-Z0-9]", "", str(v or "").upper())))


def rib_ok(v) -> bool:
    d = digits(v)
    return len(d) == 20 and int(d[3:]) % 97 == 0


def rib_parts(v) -> dict:
    """RIB 20 chiffres -> client (siège+racine, 11), siège, racine, ordinal, clé ; formule DROITE(GAUCHE(;15);11)."""
    d = digits(v)
    if len(d) != 20:
        return {}
    return {"CLIENT": d[4:15], "SIEGE": d[4:9], "RACINE": d[9:15], "ORDINAL": d[15:18], "CLE": d[18:20]}


def _part(v) -> str | None:
    if is_blank(v):
        return None
    m = re.search(r"([12])", str(v))
    return f"P{m.group(1)}" if m else None


def read(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, dtype=object)
    cols = {}
    for c in raw.columns:
        k = HEADERS.get(hkey(c))
        if k and k not in cols.values():
            cols[c] = k
    df = raw.rename(columns=cols)[list(cols.values())].copy()
    for k in REQUIRED:
        if k not in df.columns:
            raise ValueError(f"Base RH : colonne « {k} » introuvable (en-têtes : {', '.join(map(str, raw.columns))})")
    for k in set(HEADERS.values()):
        if k not in df.columns:
            df[k] = None
    df = df[df["NOM_PRENOM"].map(lambda v: not is_blank(v))].copy()
    out = df.copy()
    out["RIB"] = df["RIB"].map(digits)
    parts = out["RIB"].map(rib_parts)
    for k in ("CLIENT", "SIEGE", "RACINE", "ORDINAL", "CLE"):
        out[k] = parts.map(lambda p, k=k: p.get(k))
    for k in ("SALAIRE_POSTE", "RETENUE_SS", "IRG", "RETENUE_MUTUELLE", "SALAIRE_NET", "PART_TRANSFERABLE",
              "PART_PAYABLE"):
        out[k] = df[k].map(parse_amount)
    out["NB_JOURS"] = df["NB_JOURS"].map(lambda v: int(float(v)) if not is_blank(v) else None)
    for k in ("DATE_NAISSANCE", "DATE_ENTREE", "PERMIS_DELIVRANCE", "PERMIS_DEBUT", "PERMIS_FIN",
              "DATE_ATTESTATION", "DATE_ETABLISSEMENT"):
        out[k] = df[k].map(parse_date)
    out["IBAN"] = df["IBAN"].map(iban_clean)
    out["SWIFT"] = df["SWIFT"].map(lambda v: swift11(v) if not is_blank(v) else None)
    out["DEVISE"] = df["DEVISE"].map(lambda v: str(v).strip().upper() if not is_blank(v) else None)
    out["BENEFICIAIRE"] = [" ".join(str(x).strip() for x in (a, b) if not is_blank(x)) or None
                           for a, b in zip(df["BENEF_NOM"], df["BENEF_PRENOM"])]
    out["MOIS"] = df["MOIS_PAIEMENT"].map(lambda v: lire(v)["mois"])
    out["PART"] = df["PART"].map(_part)
    # un salarié sans PART sur une seule ligne du mois = mois complet
    out["PERIODE"] = [m + (p if isinstance(p, str) else "") if isinstance(m, str) and m else None
                      for m, p in zip(out["MOIS"], out["PART"])]
    out["MATRICULE"] = df["MATRICULE"].map(lambda v: None if is_blank(v) else str(v).strip().split(".")[0])
    out["SOURCE"] = Path(path).name
    return out.reset_index(drop=True)


def rh_dir(P) -> Path:
    return P.referentiels_dir / "base_rh"


def load_all(P) -> pd.DataFrame:
    """Toutes les bases RH déposées (une par mois) ; pour un même mois, le fichier le plus récent fait foi."""
    d = rh_dir(P)
    files = sorted((p for p in d.glob("*.xls*") if not p.name.startswith("~$")), key=lambda p: p.stat().st_mtime) \
        if d.exists() else []
    frames = []
    for p in files:
        try:
            frames.append(read(p))
        except Exception:  # noqa: BLE001  un fichier illisible n'empêche pas les autres
            continue
    if not frames:
        return pd.DataFrame(columns=list(dict.fromkeys(HEADERS.values())) + ["CLIENT", "MOIS", "PERIODE", "SOURCE"])
    df = pd.concat(frames, ignore_index=True)
    last = df.groupby("MOIS")["SOURCE"].last().to_dict()     # fichier le plus récent par mois
    return df[[last.get(m) == s for m, s in zip(df["MOIS"], df["SOURCE"])]].reset_index(drop=True)


def dq(df: pd.DataFrame, tol: float = 2.0) -> pd.DataFrame:
    """Contrôles internes de la base RH (avant tout usage) : RIB, IBAN, SWIFT, calcul de la part, jours."""
    rows = []

    def add(r, code, txt, niveau="A_VERIFIER"):
        rows.append({"NIVEAU": niveau, "CODE": code, "MATRICULE": r.get("MATRICULE"), "NOM_PRENOM": r.get("NOM_PRENOM"),
                     "CLIENT": r.get("CLIENT"), "PERIODE": r.get("PERIODE"), "ANOMALIE": txt})
    for r in df.to_dict("records"):
        if not rib_ok(r.get("RIB")):
            add(r, "RH01", f"RIB algérien invalide (clé Modulo 97) : {r.get('RIB')}", "BLOQUANT")
        ok = iban_ok(r.get("IBAN"))
        if ok is False:
            add(r, "RH02", f"IBAN invalide (clé ISO) : {r.get('IBAN')}", "BLOQUANT")
        if r.get("SWIFT") and not swift_ok(r.get("SWIFT")):
            add(r, "RH03", f"SWIFT/BIC mal formé : {r.get('SWIFT')}")
        net, part, jours, pay = r.get("SALAIRE_NET"), r.get("PART_TRANSFERABLE"), r.get("NB_JOURS"), r.get("PART_PAYABLE")
        if net and part and jours:
            att = round(PCT * net * jours / 30, 2)
            if abs(att - part) > tol:
                add(r, "RH04", f"Part transférable {part:,.2f} ≠ 95 % × net {net:,.2f} × {jours}/30 = {att:,.2f}")
        if net and part and pay and jours and abs(part + pay - net * jours / 30) > tol:
            add(r, "RH05", f"Part transférable + part payable ≠ net × {jours}/30")
        if r.get("PERMIS_FIN") and r.get("MOIS"):
            y, m = map(int, r["MOIS"].split("-"))
            debut = date(y, m, 1)
            if r["PERMIS_FIN"] < debut:
                add(r, "RH06", f"Permis échu le {r['PERMIS_FIN']:%d/%m/%Y} avant la période {r['PERIODE']}", "BLOQUANT")
        if is_blank(r.get("IBAN")) or is_blank(r.get("SWIFT")):
            add(r, "RH07", "Compte devise ou SWIFT absent", "BLOQUANT")
    # jours du mois : P1 + P2 = 30
    if not df.empty:
        for (cl, m), g in df.groupby(["CLIENT", "MOIS"]):
            if len(g) > 1 and g["NB_JOURS"].notna().all() and int(g["NB_JOURS"].sum()) != 30:
                r = g.iloc[0].to_dict()
                add(r, "RH08", f"PART 1 + PART 2 = {int(g['NB_JOURS'].sum())} jours (30 attendus)")
            if g["PART"].duplicated().any():
                add(g.iloc[0].to_dict(), "RH09", "Même PART en double pour le mois", "BLOQUANT")
    return pd.DataFrame(rows, columns=["NIVEAU", "CODE", "MATRICULE", "NOM_PRENOM", "CLIENT", "PERIODE", "ANOMALIE"])


def match(df: pd.DataFrame, client: str | None, mois: str | None, part: str | None, nom=None) -> tuple[dict | None, str]:
    """Ligne RH d'un TL : même client (RIB) et même mois ; la PART départage P1 / P2."""
    if df is None or df.empty or not mois:
        return None, ""
    c = df[df["MOIS"] == mois]
    if client:
        c2 = c[c["CLIENT"] == client]
        how = "client"
    else:
        c2 = c.iloc[0:0]
        how = ""
    if c2.empty and nom:
        sims = c["NOM_PRENOM"].map(lambda x: name_similarity(nom, x) or 0)
        c2 = c[sims >= 0.85]
        how = "nom"
    if c2.empty:
        return None, ""
    if len(c2) > 1:
        c3 = c2[c2["PART"] == part] if part else c2.iloc[0:0]
        if len(c3) == 1:
            return c3.iloc[0].to_dict(), how + " + part"
        return None, f"{how} : {len(c2)} lignes (PART à préciser)"
    return c2.iloc[0].to_dict(), how


def planning_vs_rh(planning: pd.DataFrame, df: pd.DataFrame, tol: float = 2.0) -> pd.DataFrame:
    """Chaque ligne RH du mois face au Planning TL (domiciliations contrôlées) : la DOM couvre-t-elle la période,
    la part du Planning est-elle celle de la RH, le permis est-il le même ?"""
    cols = ["STATUT", "MATRICULE", "NOM_PRENOM", "CLIENT", "PERIODE", "PART_RH", "PART_PLANNING", "ECART",
            "PERMIS_RH", "PERMIS_PLANNING", "FIN_PERMIS_RH", "NUMERO_DOMICILIATION", "DETAIL"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    pl = planning if planning is not None else pd.DataFrame()
    rows = []
    for r in df.to_dict("records"):
        out = {"MATRICULE": r.get("MATRICULE"), "NOM_PRENOM": r.get("NOM_PRENOM"), "CLIENT": r.get("CLIENT"),
               "PERIODE": r.get("PERIODE"), "PART_RH": r.get("PART_TRANSFERABLE"), "PERMIS_RH": r.get("PERMIS"),
               "FIN_PERMIS_RH": r.get("PERMIS_FIN")}
        cand = pl[pl["SIEGE_RACINE"].astype(str) == str(r.get("CLIENT"))] if not pl.empty else pl
        if cand.empty:
            out.update(STATUT="DOM_ABSENTE", DETAIL="Salarié de la base RH sans domiciliation planifiée")
            rows.append(out)
            continue
        p = cand[cand["PERIODE_TL"].astype(str) == str(r.get("PERIODE"))]
        if p.empty and not r.get("PART"):
            p = cand[cand["PERIODE_TL"].astype(str).str[:7] == str(r.get("MOIS"))]
        if p.empty:
            fin = cand["DATE_FIN_APPLICABLE"].astype(str).max() if "DATE_FIN_APPLICABLE" in cand else "?"
            out.update(STATUT="PERIODE_NON_DOMICILIEE",
                       DETAIL=f"Période {r.get('PERIODE')} hors des DOM planifiées (fin {fin}) : "
                              "DOM du nouveau contrat à domicilier ?")
            rows.append(out)
            continue
        q = p.iloc[0]
        mt = parse_amount(q.get("MONTANT_MAX_THEORIQUE"))
        out.update(PART_PLANNING=mt, PERMIS_PLANNING=q.get("NUMERO_PERMIS_TRAVAIL"),
                   NUMERO_DOMICILIATION=q.get("NUMERO_DOMICILIATION"))
        issues = []
        if mt is not None and r.get("PART_TRANSFERABLE") is not None:
            out["ECART"] = round(r["PART_TRANSFERABLE"] - mt, 2)
            if abs(out["ECART"]) > tol:
                issues.append(f"part RH {r['PART_TRANSFERABLE']:,.2f} ≠ Planning {mt:,.2f}")
        pr, pp = digits(r.get("PERMIS")), digits(q.get("NUMERO_PERMIS_TRAVAIL"))
        if pr and pp and pp not in pr:
            issues.append("n° de permis différent")
        out.update(STATUT="ECART" if issues else "OK", DETAIL=" ; ".join(issues))
        rows.append(out)
    return pd.DataFrame(rows, columns=cols)
