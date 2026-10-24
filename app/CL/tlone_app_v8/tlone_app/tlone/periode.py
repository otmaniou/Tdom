"""Lecture d'une période de transfert à partir d'un texte libre.

Une seule règle pour tout TL-One : case 70 de l'OV (« Référence du paiement et observation du donneur d'ordre »),
« Objet du transfert » de CarthagoTrade, référence de dénotage des blocages, mois de l'Annexe II.

    lire("JUIN.2026 PART2")             -> 2026-06P2
    lire("Juin 26") / lire("Sept 25 P2") -> 2026-06 / 2025-09P2
    lire("Complément janvier 2026")      -> 2026-01, complement="COMPLEMENT"
    lire("052026P1") / lire("06/2026")   -> 2026-05P1 / 2026-06
    lire("TR Août 2026 - 12 jrs")        -> 2026-08, statut A_PRECISER (12 jours sans tranche)

Résultat : {texte, periode ('AAAA-MM' | 'AAAA-MMP1' | 'AAAA-MMP2'), mois ('AAAA-MM'), tranche, jours,
complement (mot lu ou None), statut (OK | A_PRECISER | AMBIGU | ILLISIBLE | ABSENT), regle}.
"""
from __future__ import annotations

import re
import unicodedata

MOIS = {"JANVIER": 1, "JANV": 1, "JAN": 1, "FEVRIER": 2, "FEVR": 2, "FEV": 2, "MARS": 3, "MAR": 3,
        "AVRIL": 4, "AVR": 4, "MAI": 5, "JUIN": 6, "JUILLET": 7, "JUIL": 7, "AOUT": 8, "AOU": 8,
        "SEPTEMBRE": 9, "SEPT": 9, "SEP": 9, "OCTOBRE": 10, "OCT": 10, "NOVEMBRE": 11, "NOV": 11,
        "DECEMBRE": 12, "DEC": 12}
# mots qui signalent un complément à une période déjà (partiellement) transférée
COMPLEMENT_RE = re.compile(r"\b(COMPLEMENTAIRE|COMPLEMENTS?|COMPLT|COMPL|COMP|CPLT|CPL|COM|RELIQUAT|RAPPEL)\b")
_TRANCHE_RE = re.compile(
    r"(?:(?<![A-Z])P(?:ART(?:IE)?)?|\bTRANCHE|\bQUINZAINE)\s*[-_.°N]*\s*([12])(?!\d)"      # P1, PART 2, TRANCHE 1
    r"|\b([12])\s*(?:ERE|ER|EME|E|IERE|IEME)\b\s*(?:PART(?:IE)?|TRANCHE|QUINZAINE)\b")    # 1ère partie, 2ème tranche


def _up(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "nan", "none", "null", "n/a"):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).upper()
    return s


def lire(texte) -> dict:
    out = {"texte": None if texte is None else str(texte), "periode": None, "mois": None, "tranche": None,
           "jours": None, "complement": None, "statut": "ILLISIBLE", "regle": ""}
    s = _up(texte)
    if not s:
        out["statut"], out["regle"] = "ABSENT", "texte vide"
        return out
    # une date jj/mm/aaaa n'est jamais une période (souvent la date de la demande recopiée dans la case)
    s = re.sub(r"(?<!\d)\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}(?!\d)", " ", s)
    m = COMPLEMENT_RE.search(s)
    if m:
        out["complement"] = "COMPLEMENT" if m.group(1).startswith(("COMPL", "COMP", "CPL", "COM")) else m.group(1)
        s = s[:m.start()] + " " + s[m.end():]
    m = _TRANCHE_RE.search(s)
    if m:
        out["tranche"] = f"P{m.group(1) or m.group(2)}"
        s = s[:m.start()] + " " + s[m.end():]
    m = re.search(r"(\d{1,2})\s*J(?:OU)?RS?\b", s)
    if m:
        out["jours"] = int(m.group(1))
        s = s[:m.start()] + " " + s[m.end():]
    year = month = None
    for name, num in sorted(MOIS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"(?<![A-Z]){name}(?![A-Z])", s):
            month = num
            reste = re.sub(rf"(?<![A-Z]){name}(?![A-Z])", " ", s, count=1)
            y = re.search(r"(?<!\d)(20\d{2})(?!\d)", reste)
            if y:
                year, out["regle"] = int(y.group(1)), "mois en lettres"
            else:
                y = re.search(r"(?<!\d)(\d{2})(?!\d)", reste)
                if y:
                    year, out["regle"] = 2000 + int(y.group(1)), "mois en lettres, année sur 2 chiffres"
            out["regle"] = out["regle"] or "mois en lettres sans année"
            break
    if month is None:
        m = re.search(r"(?<!\d)(20\d{2})\s*[-/.]\s*(\d{1,2})(?!\d)", s) or None
        if m and 1 <= int(m.group(2)) <= 12:
            year, month, out["regle"] = int(m.group(1)), int(m.group(2)), "AAAA-MM"
        else:
            m = re.search(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(20\d{2})(?!\d)", s)
            if m and 1 <= int(m.group(1)) <= 12:
                year, month, out["regle"] = int(m.group(2)), int(m.group(1)), "MM/AAAA"
    if month is None:
        d = "".join(re.findall(r"\d+", s))
        cands = []
        if len(d) == 6:
            if 1 <= int(d[:2]) <= 12 and d[2:4] == "20":
                cands.append((int(d[2:]), int(d[:2]), "MMAAAA"))
            if d[:2] == "20" and 1 <= int(d[4:]) <= 12:
                cands.append((int(d[:4]), int(d[4:]), "AAAAMM"))
        elif len(d) == 5:
            if d[1:3] == "20" and 1 <= int(d[0]) <= 9:
                cands.append((int(d[1:]), int(d[0]), "MAAAA"))
            if d[:2] == "20" and 1 <= int(d[4]) <= 9:
                cands.append((int(d[:4]), int(d[4]), "AAAAM"))
        elif len(d) == 4 and 1 <= int(d[:2]) <= 12 and 20 <= int(d[2:]) <= 49 and re.search(r"\d{1,2}\s*[/.-]\s*\d{2}(?!\d)", s):
            cands.append((2000 + int(d[2:]), int(d[:2]), "MM/AA"))
        if len(cands) == 1:
            year, month, out["regle"] = cands[0]
        elif len(cands) > 1:
            out["statut"], out["regle"] = "AMBIGU", " ou ".join(c[2] for c in cands)
            return out
    if not (year and month and 2000 <= year <= 2100):
        out["regle"] = out["regle"] or "format non reconnu"
        return out
    out["mois"] = f"{year:04d}-{month:02d}"
    out["periode"] = out["mois"] + (out["tranche"] or "")
    out["statut"] = "OK"
    if out["jours"] is not None and not out["tranche"]:
        out["statut"] = "A_PRECISER"
        out["regle"] += f" ; {out['jours']} jours sans tranche : P1 ou P2 à préciser"
    return out
