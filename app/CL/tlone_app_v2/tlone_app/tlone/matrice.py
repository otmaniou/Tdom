"""Matrice de validation des domiciliations : données de référence × pièces.

Lignes = données de référence (nom, compte, dates, part…). Colonnes = DOM, CTS, CTR, TTR,
CarthagoDom. Chaque case porte la valeur lue (RAW), la valeur normalisée, la page, la
confiance et le statut DQ calculés par la Partie 2 (CHAMPS_DETAIL) — rien n'est ré-extrait.

Le valideur choisit la source de référence de chaque ligne (paramètre par défaut + choix par
dossier), corrige ou confirme une case, puis valide ou rejette le dossier. Ses actions sont
écrites dans un journal append-only (jamais écrasé par la Partie 2) et converties, pour le
Planning, au format des lignes A_VALIDER_MANUELLEMENT (FICHIER, CHAMP, DECISION, VALEUR_VALIDEE).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .common import (digits, dom_ref_compact, is_blank, name_similarity, norm_name, parse_amount,
                     parse_date, siege_racine)

COLS = ["DOM", "CTS", "CTR", "TTR", "CARTHAGO"]
COL_LABEL = {"DOM": "DOM", "CTS": "CTS", "CTR": "CTR", "TTR": "TTR", "CARTHAGO": "CarthagoDom"}
DOC_OF_COL = {"DOM": "ENGAGEMENT_DOMICILIATION", "CTS": "CONTRAT_SPECIFIQUE",
              "CTR": "CONTRAT_TRAVAIL", "TTR": "TITRE_TRAVAIL"}
CARTHAGO_OK = {"EXACT_DOMICILIATION_REFERENCE_MATCH"}
CARTHAGO_A_VERIFIER = {"EXACT_DOMICILIATION_REFERENCE_MATCH_TYPE_UNKNOWN"}
CARTHAGO_MSG = {
    "CARTHAGO_FILE_MISSING": "export Carthago absent",
    "SIEGE_RACINE_NOT_FOUND": "identifiant client introuvable dans le compte",
    "CLIENT_NOT_FOUND": "client absent de Carthago",
    "CARTHAGO_DOM_COLUMN_NOT_FOUND": "colonne n° de domiciliation absente de l'export",
    "NUMERO_DOMICILIATION_NOT_NORMALIZABLE": "n° de domiciliation illisible",
    "NO_EXACT_DOMICILIATION_REFERENCE_MATCH": "aucune domiciliation Carthago avec cette référence",
    "MULTIPLE_EXACT_REFERENCE_VALUES": "plusieurs références Carthago possibles",
    "EXACT_REFERENCE_PREDOM_ONLY": "trouvée seulement en PREDOM",
    "EXACT_DOMICILIATION_REFERENCE_MATCH_TYPE_UNKNOWN": "trouvée, type DOM/PREDOM inconnu",
}
CONF_LOW = 70          # en dessous : confiance faible = anomalie à vérifier
MOTIFS_REJET = ["Pièce manquante", "Titre de travail échu", "Incohérence d'identité entre pièces",
                "Dates incohérentes entre pièces", "Signature ou cachet manquant",
                "Domiciliation introuvable dans Carthago", "Montants incohérents", "Autre (préciser)"]


@dataclass(frozen=True)
class Ligne:
    key: str
    label: str
    kind: str                      # name | compte | ref | domref | date | int | amount | pct | permis | bool | info
    sources: dict                  # col -> nom de champ | ("CONCAT", f1, f2) | ("CALC", nom) | ("CARTHAGO", clé)
    ref: str | None = "CTS"        # source de référence par défaut (None : chaque case doit être conforme)
    target: str | None = None      # champ lu par le Planning (A_VALIDER_MANUELLEMENT.CHAMP)
    aug_only: bool = False
    # bornes : la colonne n'est pas comparée à l'égalité mais comme borne de validité.
    # "max" : les autres valeurs doivent être <= elle ; "min" : >= elle (titre de travail).
    bounds: tuple = ()
    vigilance: bool = False


# Lignes = données contrôlées par l'agence (tableau de correspondance métier du 17/10/2026).
LIGNES: list[Ligne] = [
    Ligne("nom", "Nom / prénom", "name",
          {"DOM": "DOM_NOM_RAISON_SOCIAL_CLIENT", "CTS": "CTS_NOM_PRENOM_TRAVAILLEUR",
           "CTR": "CTR_NOM_PRENOM_TRAVAILLEUR", "TTR": ("CONCAT", "TTR_NOM", "TTR_PRENOM"),
           "CARTHAGO": ("CARTHAGO", "CARTHAGO_NOM_COMPLET")}, "CTS", "CTS_NOM_PRENOM_TRAVAILLEUR"),
    Ligne("pere", "Nom / prénom du père", "name",
          {"CTS": "CTS_PERE_NOM_PRENOM", "CTR": "CTR_PERE_NOM_PRENOM"}, "CTS", vigilance=True),
    Ligne("mere", "Nom / prénom de la mère", "name",
          {"CTS": "CTS_MERE_NOM_PRENOM", "CTR": "CTR_MERE_NOM_PRENOM"}, "CTS", vigilance=True),
    Ligne("nationalite", "Nationalité", "name",
          {"CTS": "CTS_NATIONALITE", "CTR": "CTR_NATIONALITE", "TTR": "TTR_NATIONALITE"}, "CTS"),
    Ligne("naissance", "Date de naissance", "date",
          {"CTS": "CTS_DATE_NAISSANCE", "CTR": "CTR_DATE_NAISSANCE", "TTR": "TTR_DATE_NAISSANCE"}, "CTS"),
    Ligne("employeur", "Employeur", "name",
          {"DOM": "DOM_NOM_RAISON_SOCIAL_EMPLOYEUR", "CTS": "CTS_EMPLOYEUR", "CTR": "CTR_EMPLOYEUR",
           "TTR": "TTR_EMPLOYEUR"}, "CTS"),
    Ligne("compte", "Compte local", "compte",
          {"DOM": "DOM_COMPTE_LOCAL", "CARTHAGO": ("CARTHAGO", "CARTHAGO_CLIENT")}, "DOM",
          "DOM_COMPTE_LOCAL_NORMALIZED"),
    Ligne("agence", "Agence domiciliataire", "name",
          {"DOM": "DOM_AGENCE_DOMICILIATAIRE", "CARTHAGO": ("CARTHAGO", "CARTHAGO_AGENCE")}, "DOM"),
    Ligne("domref", "N° domiciliation", "domref",
          {"CTR": "CTR_REFERENCE_DOMICILIATION", "CARTHAGO": ("CARTHAGO", "CARTHAGO_NUM_DOM_RAW")},
          "CARTHAGO", "NUMERO_DOMICILIATION_VALIDE"),
    Ligne("contrat", "N° contrat (visa inspection)", "ref",
          {"DOM": "DOM_NUMERO_CONTRAT", "CTS": "CTS_NUMERO_CONTRAT_INSPECTION_TRAVAIL"}, "DOM"),
    Ligne("permis", "N° de permis", "permis",
          {"CTS": "CTS_NUMERO_PERMIS_TRAVAIL", "CTR": "CTR_NUMERO_PERMIS_TRAVAIL", "TTR": "TTR_NUMERO_PERMIS"},
          "CTS", "CTS_NUMERO_PERMIS_TRAVAIL"),
    Ligne("debut_permis", "Date de début", "date",
          {"DOM": "DOM_DATE_DEBUT_CONTRAT", "CTS": "CTS_DATE_DEBUT_VALIDITE_PERMIS",
           "CTR": "CTR_DATE_DEBUT_VALIDITE_PERMIS", "TTR": "TTR_DATE_DEBUT"},
          "CTS", "CTS_DATE_DEBUT_VALIDITE_PERMIS", bounds=(("TTR", "min"),)),
    Ligne("fin_permis", "Date de fin", "date",
          {"DOM": "DOM_DATE_FIN_CONTRAT", "CTS": "CTS_DATE_FIN_VALIDITE_PERMIS",
           "CTR": "CTR_DATE_FIN_VALIDITE_PERMIS", "TTR": "TTR_DATE_FIN"},
          "CTS", "CTS_DATE_FIN_VALIDITE_PERMIS", bounds=(("TTR", "max"),)),
    Ligne("duree", "Durée du contrat (mois)", "months",
          {"DOM": "DOM_DUREE_CONTRAT_MOIS", "CTS": "CTS_DUREE_MOIS", "CTR": "CTR_DUREE_MOIS", "TTR": "TTR_DUREE"},
          "CTS", bounds=(("TTR", "max"),)),
    Ligne("salaire", "Salaire net", "amount",
          {"DOM": "DOM_SALAIRE_NET_MENSUEL", "CTS": "CTS_SALAIRE_NET", "CTR": "CTR_SALAIRE_NET"},
          "CTS", "CTS_SALAIRE_NET"),
    Ligne("salaire_ancien", "Salaire net ancien", "amount", {"CTS": "CTS_SALAIRE_NET_ANCIEN"},
          "CTS", "CTS_SALAIRE_NET_ANCIEN", aug_only=True),
    Ligne("au_lieu_de", "Mention « au lieu de »", "bool", {"CTS": "CTS_MENTION_AU_LIEU_DE_PRESENTE"}, None,
          aug_only=True),
    Ligne("part", "Part transférable", "amount",
          {"DOM": "DOM_PART_TRANSFERABLE", "CTS": "CTS_PART_TRANSFERABLE"}, "CTS", "CTS_PART_TRANSFERABLE"),
    Ligne("taux", "Taux de transfert (%)", "pct",
          {"DOM": "DOM_TAUX_TRANSFERABLE", "CTS": ("CALC", "taux_cts")}, "CTS"),
    Ligne("montant", "Montant total domicilié", "amount",
          {"DOM": "DOM_MONTANT_TOTAL_DOMICILIE", "CTS": ("CALC", "montant_cts")}, "CTS"),
    Ligne("date_sig", "Date de signature / du document", "info",
          {"DOM": "DOM_DATE_SIGNATURE", "CTS": "CTS_DATE_DOCUMENT", "CTR": "CTR_DATE_SIGNATURE"}, None),
    Ligne("sig_trav", "Signature travailleur / client", "bool",
          {"DOM": "DOM_SIGNATURE_TRAVAILLEUR_PRESENTE", "CTS": "CTS_SIGNATURE_TRAVAILLEUR_PRESENTE",
           "CTR": "CTR_SIGNATURE_TRAVAILLEUR_PRESENTE"}, None),
    Ligne("lu_approuve", "Mention « lu et approuvé »", "bool",
          {"DOM": "DOM_LU_APPROUVEE_TRAVAILLEUR_PRESENTE"}, None),
    Ligne("sig_emp", "Signature employeur", "bool",
          {"CTS": "CTS_SIGNATURE_EMPLOYEUR_PRESENTE", "CTR": "CTR_SIGNATURE_EMPLOYEUR_PRESENTE"}, None),
    Ligne("cachet", "Cachet employeur", "bool",
          {"CTS": "CTS_CACHET_EMPLOYEUR_PRESENT", "CTR": "CTR_CACHET_EMPLOYEUR_PRESENT"}, None),
    Ligne("visa", "Visa inspection du travail", "bool", {"CTS": "CTS_VISA_INSPECTION_TRAVAIL_PRESENT"}, None),
    Ligne("date_visa", "Date du visa inspection", "info", {"CTS": "CTS_DATE_VISA_INSPECTION_TRAVAIL"}, None),
]
# Champs demandés par l'agence mais pas encore extraits par la Partie 1 V15-A (à ajouter au prompt).
CHAMPS_A_EXTRAIRE = {"DOM_SIGNATURE_TRAVAILLEUR_PRESENTE", "DOM_LU_APPROUVEE_TRAVAILLEUR_PRESENTE",
                     "CTS_NUMERO_CONTRAT_INSPECTION_TRAVAIL", "CTS_DATE_VISA_INSPECTION_TRAVAIL"}
LIGNE_BY_KEY = {lg.key: lg for lg in LIGNES}
RULES = {
    "name": "Majuscules, accents retirés ; comparaison insensible à l'ordre nom/prénom",
    "compte": "20 chiffres, préfixe 02700, clé Modulo 97 ; Carthago : identifiant client (siège 07310…)",
    "ref": "Référence de l'encart ministère, comparée sans espaces ni ponctuation",
    "domref": "Tous les chiffres + suffixe DZD (règle Partie 2)",
    "date": "JJ/MM/AAAA (jour en premier)", "int": "Nombre entier de mois",
    "amount": "Montant DZD, séparateurs « : » et espaces retirés, tolérance 0,01",
    "pct": "Pourcentage, tolérance 0,5 point", "permis": "Numéro comparé sans espaces ni ponctuation",
    "bool": "Présence détectée sur la page",
    "months": "Nombre de mois (TTR : « 2 ANS, 0 JOURS » converti en mois)",
    "info": "Information affichée, sans comparaison entre pièces",
}
RULES_LIGNE = {
    "compte": "Client Carthago = DROITE(GAUCHE(compte;15);11), soit le motif 07310 + 6 chiffres ; clé Modulo 97",
    "permis": "Format AA-00000000 / WW-AA-000000 (AA : année de la demande ; WW : wilaya, AA : année de "
              "délivrance) ; « / » accepté à la place de « - »",
    "debut_permis": "CTS = DOM = CTR ; CTS ≥ date de début du TTR",
    "fin_permis": "CTS = DOM = CTR ; CTS ≤ date de fin du TTR",
    "duree": "Durée CTS = DOM = CTR = écart entre les dates de début et de fin ; CTS ≤ durée du TTR",
    "part": f"CTS ≤ {os.environ.get('TLONE_PLAFOND_PCT_NET', '0.95')} × salaire net CTS",
    "taux": "Taux DOM = part transférable CTS ÷ salaire net CTS",
    "montant": "Montant DOM = part transférable CTS × durée CTS (mois)",
    "pere": "Vigilance", "mere": "Vigilance",
}


# ----------------------------------------------------------------------------- valeurs
def _txt(v) -> str | None:
    if is_blank(v):
        return None
    s = str(v).strip()
    return s if s and s.upper() not in ("NONE", "NULL", "NAN", "N/A") else None


def to_bool(v) -> bool | None:
    if is_blank(v):
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().upper()
    if s in ("TRUE", "VRAI", "OUI", "YES", "1", "PRESENT", "PRÉSENT", "PRESENTE", "PRÉSENTE"):
        return True
    if s in ("FALSE", "FAUX", "NON", "NO", "0", "ABSENT", "ABSENTE"):
        return False
    return None


def fmt_amount(v) -> str | None:
    a = parse_amount(v)
    return None if a is None else f"{a:,.2f}".replace(",", " ").replace(".", ",")


def fmt_date(v) -> str | None:
    d = parse_date(v)
    return d.strftime("%d/%m/%Y") if d else _txt(v)


def to_int(v) -> int | None:
    a = parse_amount(v)
    return None if a is None else int(round(a))


def to_pct(v) -> float | None:
    if is_blank(v):
        return None
    a = parse_amount(str(v).replace("%", ""))
    if a is None:
        return None
    return a * 100 if 0 < a <= 1 else a


_RE_DEMANDE = re.compile(r"(?<!\d)(\d{2})\s*[-/]\s*(\d{8})(?!\d)")
_RE_PERMIS = re.compile(r"(?<!\d)(\d{2})\s*[-/]\s*(\d{2})\s*[-/]\s*(\d{6})(?!\d)")


def permis_parts(v) -> tuple[str | None, str | None]:
    """« 20-00010423/31-26-000472 » -> ('20-00010423', '31-26-000472') : n° de demande, n° de permis."""
    if is_blank(v):
        return None, None
    s = str(v)
    p = _RE_PERMIS.search(s)
    rest = s[:p.start()] + " " + s[p.end():] if p else s
    d = _RE_DEMANDE.search(rest)
    return (f"{d.group(1)}-{d.group(2)}" if d else None,
            f"{p.group(1)}-{p.group(2)}-{p.group(3)}" if p else None)


def to_months(v) -> int | None:
    """24 / « 24 mois » / « 2 ANS, 0 JOURS » / « 1 AN 6 MOIS » -> mois."""
    if is_blank(v):
        return None
    s = strip_accents_up(str(v))
    if not re.search(r"AN|MOIS|JOUR", s):
        return to_int(v)
    ans = re.search(r"(\d+)\s*ANS?\b", s)
    mois = re.search(r"(\d+)\s*MOIS", s)
    jours = re.search(r"(\d+)\s*JOURS?", s)
    total = (int(ans.group(1)) * 12 if ans else 0) + (int(mois.group(1)) if mois else 0)
    if jours and int(jours.group(1)) >= 15:
        total += 1
    return total if (ans or mois) else None


def strip_accents_up(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).upper()


def months_between(d1: date, d2: date) -> int:
    """Durée en mois entre une date de début et une date de fin incluse (03/01/2026 -> 02/01/2028 = 24)."""
    end = d2 + timedelta(days=1)
    m = (end.year - d1.year) * 12 + (end.month - d1.month)
    return m + (1 if end.day - d1.day >= 15 else -1 if d1.day - end.day >= 15 else 0)


def display(kind: str, v) -> str | None:
    if kind == "amount":
        return fmt_amount(v)
    if kind == "date":
        return fmt_date(v)
    if kind == "int":
        i = to_int(v)
        return None if i is None else str(i)
    if kind == "pct":
        p = to_pct(v)
        return None if p is None else f"{p:.1f} %".replace(".", ",")
    if kind == "bool":
        b = to_bool(v)
        return None if b is None else ("Présente" if b else "Absente")
    if kind == "months":
        n = to_months(v)
        return None if n is None else f"{n} mois" + ("" if re.fullmatch(r"[\d.,\s]+", str(v).strip()) else f" ({v})")
    if kind == "permis":
        dmd, prm = permis_parts(v)
        return " / ".join(x for x in (dmd, prm) if x) if (dmd or prm) else _txt(v)
    if kind == "info":
        return fmt_date(v) if parse_date(v) else _txt(v)
    return _txt(v)


def same(kind: str, a, b) -> tuple[bool | None, str]:
    """Compare deux valeurs d'une même ligne. (None, '') si non comparable."""
    if is_blank(a) or is_blank(b):
        return None, ""
    if kind == "name":
        if norm_name(a) == norm_name(b):
            return True, ""
        sim = name_similarity(a, b) or 0
        return False, f"similarité {sim:.0%}"
    if kind == "compte":
        da, db = digits(a), digits(b)
        if len(da) == 20 and len(db) == 20:
            return da == db, ""
        sa, sb = siege_racine(da) or da, siege_racine(db) or db
        return sa == sb, "identifiant client"
    if kind == "domref":
        return dom_ref_compact(a) == dom_ref_compact(b), ""
    if kind == "permis":
        (da, pa), (db, pb) = permis_parts(a), permis_parts(b)
        if not (da or pa) or not (db or pb):  # format non reconnu : comparaison brute
            ka, kb = re.sub(r"[^0-9]", "", str(a)), re.sub(r"[^0-9]", "", str(b))
            return ka == kb, ""
        diffs = [lab for lab, x, y in (("n° de permis", pa, pb), ("n° de demande", da, db)) if x and y and x != y]
        return (not diffs), ", ".join(f"{d} différent" for d in diffs)
    if kind == "months":
        ia, ib = to_months(a), to_months(b)
        return (None, "") if ia is None or ib is None else (ia == ib, "")
    if kind == "info":
        return None, ""
    if kind == "ref":
        ka, kb = re.sub(r"[^0-9A-Z]", "", str(a).upper()), re.sub(r"[^0-9A-Z]", "", str(b).upper())
        return (ka == kb or (len(min(ka, kb, key=len)) >= 6 and (ka in kb or kb in ka))), ""
    if kind == "date":
        da, db = parse_date(a), parse_date(b)
        return (None, "") if da is None or db is None else (da == db, "")
    if kind == "int":
        ia, ib = to_int(a), to_int(b)
        return (None, "") if ia is None or ib is None else (ia == ib, "")
    if kind == "amount":
        fa, fb = parse_amount(a), parse_amount(b)
        return (None, "") if fa is None or fb is None else (abs(fa - fb) <= 0.01, "")
    if kind == "pct":
        pa, pb = to_pct(a), to_pct(b)
        return (None, "") if pa is None or pb is None else (abs(pa - pb) <= 0.5, "")
    return str(a).strip().upper() == str(b).strip().upper(), ""


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


# ----------------------------------------------------------------------------- lot
@dataclass
class Lot:
    dossiers: pd.DataFrame
    fields: pd.DataFrame
    carthago: pd.DataFrame
    source: str = ""
    by_file: dict = field(default_factory=dict)
    champs_connus: set = field(default_factory=set)   # champs présents dans CHAMPS_DETAIL (Partie 2)


def _read(csv: Path, xlsx: Path, sheet: str) -> pd.DataFrame:
    if csv.exists():
        return pd.read_csv(csv, dtype=object, encoding="utf-8-sig")
    if xlsx.exists():
        try:
            return pd.read_excel(xlsx, sheet_name=sheet, dtype=object)
        except ValueError:
            return pd.DataFrame()
    return pd.DataFrame()


def load_lot(P) -> Lot:
    """Charge les sorties de la Partie 2 (CSV si présents, sinon feuilles du classeur)."""
    dos = _read(P.dossiers_csv, P.validation_xlsx, "DOSSIERS_A_VALIDER")
    fld = _read(P.fields_csv, P.validation_xlsx, "CHAMPS_DETAIL")
    car = _read(P.carthago_match_csv, P.validation_xlsx, "CARTHAGO_MATCH")
    lot = Lot(dos, fld, car, source=str(P.fields_csv if P.fields_csv.exists() else P.validation_xlsx))
    if not fld.empty and "FICHIER" in fld.columns:
        lot.by_file = {k: g for k, g in fld.groupby(fld["FICHIER"].astype(str))}
        lot.champs_connus = set(fld["CHAMP"].astype(str)) if "CHAMP" in fld.columns else set()
    return lot


# ----------------------------------------------------------------------------- journal
def read_journal(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def append_event(path: Path, user: str, fichier: str, action: str, **kw) -> dict:
    ev = {"ts": datetime.now().isoformat(timespec="seconds"), "user": user, "fichier": fichier,
          "action": action, **kw}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    return ev


def fold(events: list[dict]) -> dict:
    """État courant par dossier : cases (corrigé / confirmé), sources choisies, décision."""
    st: dict = {}
    for ev in events:
        d = st.setdefault(str(ev.get("fichier")), {"cells": {}, "sources": {}, "decision": None, "history": []})
        a = ev.get("action")
        if a in ("CORRIGE", "CONFIRME", "ANNULE"):
            k = f"{ev.get('ligne')}|{ev.get('col')}"
            if a == "ANNULE":
                d["cells"].pop(k, None)
            else:
                d["cells"][k] = ev
        elif a == "SOURCE":
            d["sources"][ev.get("ligne")] = ev.get("col")
        elif a in ("VALIDE", "REJETE"):
            d["decision"] = ev
        elif a == "ROUVERT":
            d["decision"] = None
        d["history"].append(ev)
    return st


# ----------------------------------------------------------------------------- sources de référence
def default_sources(path: Path | None = None) -> dict:
    """Source par ligne : paramètre (referentiels/sources_reference_dom.xlsx) sinon défaut du code."""
    out = {lg.key: lg.ref for lg in LIGNES}
    if path and path.exists():
        try:
            df = pd.read_excel(path, dtype=str)
            for _, r in df.iterrows():
                k, c = _txt(r.get("LIGNE")), _txt(r.get("SOURCE_REFERENCE"))
                if k in out and c in COLS and c in LIGNE_BY_KEY[k].sources:
                    out[k] = c
        except Exception:
            pass
    return out


def sources_table(path: Path | None = None) -> pd.DataFrame:
    cur = default_sources(path)
    return pd.DataFrame([{"LIGNE": lg.key, "DONNEE": lg.label, "SOURCE_REFERENCE": cur[lg.key] or "",
                          "SOURCES_POSSIBLES": ", ".join(lg.sources), "ALIMENTE_LE_PLANNING": lg.target or ""}
                         for lg in LIGNES if lg.ref])


# ----------------------------------------------------------------------------- construction
def _field_info(g: pd.DataFrame | None, champ: str) -> dict | None:
    if g is None or g.empty:
        return None
    rows = g[g["CHAMP"].astype(str) == champ]
    if rows.empty:
        return None
    filled = rows[rows["NORMALIZED"].map(lambda v: not is_blank(v))] if "NORMALIZED" in rows else rows
    r = (filled if not filled.empty else rows).iloc[0]

    def gv(k):
        v = r.get(k)
        return None if is_blank(v) else v
    conf = gv("FIELD_CONFIDENCE")
    try:
        conf = None if conf is None else float(conf)
    except (TypeError, ValueError):
        conf = None
    page = gv("PAGE")
    try:
        page = None if page is None else int(float(page))
    except (TypeError, ValueError):
        page = None
    return {"raw": gv("RAW"), "norm": gv("NORMALIZED"), "page": page, "conf": conf,
            "level": gv("FIELD_CONFIDENCE_LEVEL"), "dq": gv("DQ_STATUS_FIELD"), "dq_reason": gv("DQ_REASON"),
            "dq_anom": gv("DQ_ANOMALIES"), "msg": gv("NORMALIZATION_MESSAGE"), "rule": gv("NORMALIZATION_RULE"),
            "importance": gv("DQ_IMPORTANCE"), "doc": gv("TYPE_DOCUMENT")}


def _carthago_row(lot: Lot, fichier: str) -> dict:
    c = lot.carthago
    if c.empty or "FICHIER" not in c.columns:
        return {}
    g = c[c["FICHIER"].astype(str) == fichier]
    if g.empty:
        return {}
    if "REFERENCE_EXACT_MATCH" in g.columns:
        ex = g[g["REFERENCE_EXACT_MATCH"].map(lambda v: str(v).strip().upper() in ("TRUE", "1", "VRAI"))]
        if not ex.empty:
            g = ex
    return {k: (None if is_blank(v) else v) for k, v in g.iloc[0].to_dict().items()}


def _calc(name: str, row: dict) -> str | None:
    if name in ("fin_cts", "fin_ctr"):
        p = "CTS" if name == "fin_cts" else "CTR"
        d, n = parse_date(row.get(f"{p}_DATE_DEBUT_CONTRAT")), to_int(row.get(f"{p}_DUREE_MOIS"))
        return (add_months(d, n) - timedelta(days=1)).strftime("%d/%m/%Y") if d and n else None
    if name == "taux_cts":
        part, sal = parse_amount(row.get("CTS_PART_TRANSFERABLE")), parse_amount(row.get("CTS_SALAIRE_NET"))
        return f"{part / sal * 100:.2f}" if part and sal else None
    if name == "montant_cts":
        part, n = parse_amount(row.get("CTS_PART_TRANSFERABLE")), to_int(row.get("CTS_DUREE_MOIS"))
        return f"{part * n:.2f}" if part and n else None
    return None


def _calc_ctx(name: str, ctx: dict) -> str | None:
    part = parse_amount(ctx.get("part", {}).get("CTS"))
    if name == "taux_cts":
        sal = parse_amount(ctx.get("salaire", {}).get("CTS"))
        return f"{part / sal * 100:.2f}" if part and sal else None
    if name == "montant_cts":
        n = to_months(ctx.get("duree", {}).get("CTS"))
        return f"{part * n:.2f}" if part and n else None
    return None


def _cell(lot: Lot, lg: Ligne, col: str, row: dict, g, car: dict) -> dict:
    spec = lg.sources.get(col)
    base = {"col": col, "ligne": lg.key, "present": False, "raw": None, "value": None, "page": None, "conf": None,
            "level": None, "computed": False, "issues": [], "dq": None, "doc": DOC_OF_COL.get(col)}
    if spec is None:
        return base
    if isinstance(spec, tuple) and spec[0] == "CALC":
        v = _calc(spec[1], row)
        base.update(present=v is not None, value=v, raw=v, computed=True)
        return base
    if isinstance(spec, tuple) and spec[0] == "CARTHAGO":
        v = car.get(spec[1])
        status = _txt(row.get("CARTHAGO_MATCH_STATUS"))
        if spec[1] == "CARTHAGO_NUM_DOM_RAW" and is_blank(v) and status in CARTHAGO_OK | CARTHAGO_A_VERIFIER:
            v = row.get("NUMERO_DOMICILIATION_PROPOSE")
        if spec[1] == "CARTHAGO_CLIENT" and is_blank(v) and _txt(row.get("CARTHAGO_CLIENT_MATCH")) in ("True", "TRUE", "1"):
            v = row.get("SIEGE_RACINE")
        base.update(present=True, value=_txt(v), raw=_txt(v), carthago_status=status)
        if lg.key == "domref" and status and status not in CARTHAGO_OK:
            base["issues"].append(("verif" if status in CARTHAGO_A_VERIFIER else "bloq",
                                   f"Carthago : {CARTHAGO_MSG.get(status, status)}"))
        if lg.key == "domref" and is_blank(v) and not status:
            base["issues"].append(("bloq", "Domiciliation non trouvée dans Carthago"))
        return base
    if isinstance(spec, tuple) and spec[0] == "CONCAT":
        parts = [_field_info(g, f) for f in spec[1:]]
        if not any(parts):
            vals = [_txt(row.get(f)) for f in spec[1:]]
            if not any(vals):
                return base
            base.update(present=True, value=" ".join(v for v in vals if v), raw=" ".join(v for v in vals if v))
            return base
        info = next(p for p in parts if p)
        norm = " ".join(str(p["norm"]) for p in parts if p and not is_blank(p["norm"])) or None
        raw = " ".join(str(p["raw"]) for p in parts if p and not is_blank(p["raw"])) or None
        confs = [p["conf"] for p in parts if p and p["conf"] is not None]
        info = dict(info, norm=norm, raw=raw, conf=min(confs) if confs else None)
    else:
        info = _field_info(g, spec)
        if info is None:  # pas de CHAMPS_DETAIL : valeur consolidée du dossier
            v = _txt(row.get(spec))
            if v is None:
                return base
            base.update(present=True, value=v, raw=v)
            return base
    value = info["norm"]
    if lg.kind == "bool" and spec == "DOM_DATE_SIGNATURE":  # présence déduite de la date de signature
        value = None if is_blank(info["norm"]) else True
        base["note"] = f"Datée du {fmt_date(info['norm'])}" if value else None
    base.update(present=True, raw=info["raw"], value=value, page=info["page"], conf=info["conf"],
                level=info["level"], dq=info["dq"], dq_reason=info["dq_reason"], msg=info["msg"],
                rule=info["rule"])
    if info["dq"] in ("BLOCKED", "REVIEW"):
        base["issues"].append(("incoh" if info["dq"] == "BLOCKED" else "verif",
                               f"Partie 2 : {info['dq_reason'] or info['dq_anom'] or info['dq']}"))
    if info["conf"] is not None and info["conf"] < CONF_LOW and not is_blank(value):
        base["issues"].append(("verif", f"Confiance faible ({info['conf']:.0f})"))
    return base


def compte_issues(v) -> list[tuple[str, str]]:
    """Règles Partie 2 (analyze_dom_compte_local) recalculées sur la valeur courante (lue ou corrigée)."""
    d = digits(v)
    if not d:
        return []
    out = []
    if len(d) != 20:
        out.append(("bloq", f"Compte de {len(d)} chiffres (20 attendus)"))
        return out
    if not d.startswith("02700"):
        out.append(("verif", "Préfixe 02700 absent"))
    m = list(re.finditer(r"07310(\d{6})", d))
    if len(m) != 1:
        out.append(("verif", "Identifiant client 07310… introuvable ou ambigu"))
    elif d[m[0].end():m[0].end() + 3] != "001":
        out.append(("verif", "Ordinal 001 absent après l'identifiant client"))
    base, cle = d[3:18], d[18:20]
    if int(base + cle) % 97 != 0:
        out.append(("bloq", f"Clé Modulo 97 invalide : lue {cle}, attendue {97 - (int(base) * 100) % 97:02d}"))
    return out


def _value_issues(lg: Ligne, col: str, cell: dict) -> list[tuple[str, str]]:
    """Contrôles portant sur la valeur elle-même : refaits après chaque correction."""
    v = cell["value"]
    if lg.kind == "bool" and to_bool(v) is False:
        return [("bloq", "Absente alors qu'attendue")]
    if lg.key == "compte" and col == "DOM":
        return compte_issues(v)
    if lg.kind == "permis":
        dmd, prm = permis_parts(v)
        if not prm:
            return [("verif", "Format inattendu (attendu AA-00000000 / WW-AA-000000)")]
    return []


def _cross_issues(lg: Ligne, cells: dict, ctx: dict) -> None:
    """Règles entre lignes, sur les valeurs courantes (après corrections). ctx[ligne][col] = valeur."""
    if lg.key == "part":
        part, sal = parse_amount(cells["CTS"].get("value")), parse_amount(ctx.get("salaire", {}).get("CTS"))
        pct = float(os.environ.get("TLONE_PLAFOND_PCT_NET", "0.95"))
        if part is not None and sal and part > sal * pct + 0.01:
            cells["CTS"]["issues"].append(("bloq", f"Part {fmt_amount(part)} > {pct:.0%} du salaire net "
                                                   f"({fmt_amount(sal * pct)})"))
    if lg.key == "duree":
        d1 = parse_date(ctx.get("debut_permis", {}).get("CTS"))
        d2 = parse_date(ctx.get("fin_permis", {}).get("CTS"))
        n = to_months(cells["CTS"].get("value"))
        if d1 and d2 and n is not None and months_between(d1, d2) != n:
            cells["CTS"]["issues"].append(("verif", f"Durée {n} mois ≠ écart des dates ({months_between(d1, d2)} mois "
                                                    f"du {d1:%d/%m/%Y} au {d2:%d/%m/%Y})"))


def build(lot: Lot, fichier: str, state: dict | None = None, sources: dict | None = None) -> dict:
    """Matrice complète d'un dossier, avec valeurs retenues et anomalies encore ouvertes."""
    rows = lot.dossiers[lot.dossiers["FICHIER"].astype(str) == fichier]
    row = {k: (None if is_blank(v) else v) for k, v in (rows.iloc[0].to_dict() if not rows.empty else {}).items()}
    g = lot.by_file.get(fichier)
    if g is not None and not g.empty:  # valeurs lues par pièce : base des valeurs calculées (fin, taux, montant)
        for ch, v in zip(g["CHAMP"].astype(str), g["NORMALIZED"]):
            if is_blank(row.get(ch)) and not is_blank(v):
                row[ch] = v
    car = _carthago_row(lot, fichier)
    state = state or {"cells": {}, "sources": {}, "decision": None, "history": []}
    src = dict(sources or default_sources())
    src.update({k: v for k, v in state.get("sources", {}).items() if k in LIGNE_BY_KEY})
    aug = str(row.get("TYPE_DOSSIER") or "").upper() == "AUGMENTATION"
    out_rows = []
    n_open = 0
    ctx: dict = {}
    for lg in LIGNES:
        if lg.aug_only and not aug:
            continue
        cells = {c: _cell(lot, lg, c, row, g, car) for c in COLS}
        # corrections / confirmations du valideur
        for c, cell in cells.items():
            ev = state["cells"].get(f"{lg.key}|{c}")
            cell["edit"] = None
            if ev and ev["action"] == "CORRIGE":
                cell["edit"] = ev
                cell["value"] = ev.get("valeur")
                cell["present"] = True
                cell["issues"] = []  # la lecture OCR est remplacée : ses alertes tombent
            elif ev and ev["action"] == "CONFIRME":
                if str(ev.get("valeur_vue")) == str(cell["value"]):
                    cell["edit"] = ev
                # sinon : la valeur a changé depuis la confirmation (nouvelle Partie 2) -> à revoir
        for c, cell in cells.items():
            spec = lg.sources.get(c)
            if cell["computed"] and isinstance(spec, tuple):  # recalcul sur les valeurs courantes (corrigées)
                v = _calc_ctx(spec[1], ctx)
                cell.update(value=v, raw=v, present=v is not None)
            if cell["present"] and not is_blank(cell["value"]):
                cell["issues"] += _value_issues(lg, c, cell)
            # « à extraire » tant que la Partie 1/2 ne produit pas ce champ ; dès qu'il apparaît dans
            # CHAMPS_DETAIL, la case s'affiche et se contrôle comme les autres (aucun code à changer).
            cell["a_extraire"] = (isinstance(spec, str) and spec in CHAMPS_A_EXTRAIRE and is_blank(cell["value"])
                                  and spec not in lot.champs_connus)
        ctx[lg.key] = {c: cell["value"] for c, cell in cells.items()}
        _cross_issues(lg, cells, ctx)
        ref = src.get(lg.key) if lg.ref else None
        if ref and (ref not in lg.sources):
            ref = lg.ref
        retenu = cells[ref]["value"] if ref else None
        bounds = dict(lg.bounds)
        if ref:
            for c, cell in cells.items():
                if c == ref or not cell["present"] or is_blank(cell["value"]):
                    continue
                disp = display(lg.kind, retenu) or retenu
                bound_col, other = (c, retenu) if c in bounds else ((ref, cell["value"]) if ref in bounds else (None, None))
                if bound_col:  # TTR : borne de validité, pas égalité
                    kind_b = bounds[bound_col]
                    if lg.kind == "date":
                        bv, ov = parse_date(cells[bound_col]["value"]), parse_date(other)
                    else:
                        bv, ov = to_months(cells[bound_col]["value"]), to_months(other)
                    if bv is None or ov is None:
                        continue
                    bad = ov > bv if kind_b == "max" else ov < bv
                    if bad:
                        sens = "après la fin" if kind_b == "max" else "avant le début"
                        if lg.kind == "months":
                            sens = "supérieure à celle"
                        cell["issues"].append(("incoh", f"{COL_LABEL[ref if c in bounds else c]} {display(lg.kind, other)} "
                                                        f"{sens} du TTR ({display(lg.kind, cells[bound_col]['value'])})"))
                    continue
                ok, why = same(lg.kind, cell["value"], retenu)
                if ok is False:
                    cell["issues"].append(("incoh", f"Différent de {COL_LABEL[ref]} ({disp})" + (f" — {why}" if why else "")))
        for cell in cells.values():
            bloq = any(k == "bloq" for k, _ in cell["issues"])
            cell["bloq"] = bloq
            # une confirmation ne lève pas une anomalie bloquante ; une correction est re-contrôlée
            confirmed = cell["edit"] is not None and cell["edit"]["action"] == "CONFIRME"
            cell["open"] = bool(cell["issues"]) and (bloq or not confirmed)
            cell["text"] = display(lg.kind, cell["value"]) if not is_blank(cell["value"]) else None
            if cell.get("note") and cell["text"]:
                cell["text"] = cell["note"]
            if cell["computed"] and cell["text"]:
                cell["text"] += " (calculé)"
        missing_ref = bool(lg.target) and is_blank(retenu)
        opens = [c for c in cells.values() if c["open"]]
        n_open += len(opens) + (1 if missing_ref else 0)
        if missing_ref:
            coh = "✗ à choisir"
        elif any(c["bloq"] for c in opens):
            coh = "✗ bloquant"
        elif any(k == "incoh" for c in opens for k, _ in c["issues"]):
            coh = "✗ écart"
        elif opens:
            coh = "à vérifier"
        else:
            coh = "✓"
        out_rows.append({"ligne": lg, "cells": cells, "ref": ref, "retenu": retenu,
                         "retenu_txt": display(lg.kind, retenu) if not is_blank(retenu) else None,
                         "missing_ref": missing_ref, "coh": coh, "n_open": len(opens) + (1 if missing_ref else 0)})
    n_bloq = sum(1 for x in out_rows for c in x["cells"].values() if c["open"] and c["bloq"])
    return {"fichier": fichier, "row": row, "rows": out_rows, "n_open": n_open, "n_bloq": n_bloq, "aug": aug,
            "decision": state.get("decision"), "history": state.get("history", []), "carthago": car}


def summary(m: dict) -> dict:
    """Une ligne de la liste des dossiers."""
    r, byk = m["row"], {x["ligne"].key: x for x in m["rows"]}

    def ret(k):
        x = byk.get(k)
        return x["retenu_txt"] if x else None

    def red(k):
        x = byk.get(k)
        return bool(x and x["n_open"])
    dec = m["decision"]
    if dec and dec["action"] == "VALIDE":
        statut, feu = "Validé", "v"
    elif dec and dec["action"] == "REJETE":
        statut, feu = f"Rejeté — {dec.get('motif') or ''}".strip(" —"), "x"
    else:
        incoh = any(k in ("incoh", "bloq") for x in m["rows"] for c in x["cells"].values() if c["open"]
                    for k, _ in c["issues"])
        statut = "À traiter" if m["n_open"] else "Prêt à valider"
        feu = "r" if (incoh or any(x["missing_ref"] for x in m["rows"])) else ("o" if m["n_open"] else "v")
    car_st = _txt(r.get("CARTHAGO_MATCH_STATUS"))
    dq = r.get("DQ_SCORE")
    try:
        dq = None if dq is None else round(float(dq))
    except (TypeError, ValueError):
        dq = None
    taux = byk.get("taux")
    taux_txt = (taux["retenu_txt"] or (taux["cells"]["CTS"]["text"] if taux else None)) if taux else None
    return {
        "FICHIER": m["fichier"], "FEU": feu, "NOM": ret("nom") or _txt(r.get("NOM_TRAVAILLEUR_REFERENCE")),
        "COMPTE": ret("compte") or _txt(r.get("DOM_COMPTE_LOCAL_NORMALIZED")),
        "IDENTIFIANT_CLIENT": _txt(r.get("SIEGE_RACINE")) or siege_racine(ret("compte")),
        "DEBUT": ret("debut_permis"), "FIN": ret("fin_permis"), "PART": ret("part"), "TAUX": taux_txt,
        "PERMIS": ret("permis"),
        "TYPE": "Augmentation" + (f" {r.get('AUGMENTATION_YEAR')}" if not is_blank(r.get("AUGMENTATION_YEAR")) else "")
        if m["aug"] else "Nouveau contrat",
        "FIABILITE": dq, "A_REVOIR": m["n_open"], "BLOQUANTS": m["n_bloq"],
        "CARTHAGO": "Confirmé" if car_st in CARTHAGO_OK else ("Non trouvé" if car_st else "—"),
        "STATUT": statut,
        "_red": {k: red(k) for k in ("debut_permis", "fin_permis", "part", "taux", "permis", "nom", "compte")},
    }


def build_all(lot: Lot, journal: list[dict], sources: dict) -> list[dict]:
    st = fold(journal)
    if lot.dossiers.empty or "FICHIER" not in lot.dossiers.columns:
        return []
    return [build(lot, str(f), st.get(str(f)), sources) for f in lot.dossiers["FICHIER"].astype(str)]


# ----------------------------------------------------------------------------- vers le Planning
def _planning_value(kind: str, v) -> str | None:
    if is_blank(v):
        return None
    if kind == "amount":
        a = parse_amount(v)
        return None if a is None else f"{a:.2f}"
    if kind == "date":
        return fmt_date(v)
    if kind == "compte":
        return digits(v) or str(v)
    if kind == "domref":
        return dom_ref_compact(v)
    return str(v).strip()


def planning_rows(matrices: list[dict]) -> pd.DataFrame:
    """Décisions de l'app au format A_VALIDER_MANUELLEMENT (lu par planning.apply_manual)."""
    out = []
    for m in matrices:
        dec = m["decision"]
        if not dec:
            continue
        base = {"FICHIER": m["fichier"], "TYPE_DOSSIER": m["row"].get("TYPE_DOSSIER"), "SOURCE": "APP_MATRICE",
                "VALIDEUR": dec.get("user"), "HORODATAGE": dec.get("ts")}
        if dec["action"] == "REJETE":
            out.append(dict(base, CHAMP="DOSSIER", DECISION_MANUELLE="REJETEE",
                            COMMENTAIRE=f"{dec.get('motif') or ''} {dec.get('commentaire') or ''}".strip()))
            continue
        for x in m["rows"]:
            lg = x["ligne"]
            if not lg.target:
                continue
            v = _planning_value(lg.kind, x["retenu"])
            cur = m["row"].get(lg.target)
            ok, _ = same(lg.kind, v, cur)
            out.append(dict(base, CHAMP=lg.target, VALEUR_VALIDEE=v,
                            DECISION_MANUELLE="VALIDEE" if ok else "CORRIGEE",
                            COMMENTAIRE=f"source {COL_LABEL.get(x['ref'], x['ref'])}"))
    cols = ["FICHIER", "TYPE_DOSSIER", "CHAMP", "VALEUR_VALIDEE", "DECISION_MANUELLE", "COMMENTAIRE",
            "SOURCE", "VALIDEUR", "HORODATAGE"]
    return pd.DataFrame(out, columns=cols)


def merge_manual(manual_xlsx: pd.DataFrame, app_rows: pd.DataFrame) -> pd.DataFrame:
    """Lignes du classeur Partie 2 + décisions de l'app (les secondes l'emportent, appliquées en dernier).

    Pour un dossier décidé dans l'app, ses lignes du classeur restées sans décision sont
    considérées comme acceptées : la matrice a exigé que toutes les anomalies soient traitées.
    """
    man = manual_xlsx.copy() if manual_xlsx is not None else pd.DataFrame()
    if app_rows is None or app_rows.empty:
        return man
    decided = set(app_rows["FICHIER"].astype(str))
    if not man.empty and "FICHIER" in man.columns:
        if "DECISION_MANUELLE" not in man.columns:
            man["DECISION_MANUELLE"] = None
        m = man["FICHIER"].astype(str).isin(decided) & man["DECISION_MANUELLE"].map(is_blank)
        man.loc[m, "DECISION_MANUELLE"] = "VALIDEE"
    return pd.concat([man, app_rows], ignore_index=True, sort=False)


# ----------------------------------------------------------------------------- page PDF
def page_rotation(raw_json_dir: Path, fichier: str, page: int | None) -> int:
    """Rotation appliquée par la Partie 1 à cette page (pour l'afficher redressée)."""
    if page is None or not raw_json_dir.is_dir():
        return 0
    stem = Path(fichier).stem.lower()
    for p in raw_json_dir.glob("*.json"):
        if stem not in p.stem.lower():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(d.get("source_file")) != fichier:
            continue
        for rec in d.get("page_records") or []:
            if rec.get("page_num") == page:
                for k in ("rotation_clockwise_applied", "rotation_clockwise"):
                    try:
                        if rec.get(k) is not None:
                            return int(rec[k]) % 360
                    except (TypeError, ValueError):
                        pass
        return 0
    return 0
