"""Conversion d'un montant en lettres (français) en nombre — contrôle CTL-09.

« UN MILLION DEUX CENT SOIXANTE ET UN MILLE SIX CENTS DINARS ALGERIENS ET 50 CTS »
-> 1261600.50. Retourne None si la phrase n'est pas interprétable : le contrôle
passe alors en revue humaine, jamais en rejet.
"""
from __future__ import annotations

import re
import unicodedata

UNITS = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
    "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13,
    "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20, "trente": 30,
    "quarante": 40, "cinquante": 50, "soixante": 60, "septante": 70, "octante": 80,
    "huitante": 80, "nonante": 90,
}
SCALES = {"mille": 1_000, "milles": 1_000, "million": 1_000_000, "millions": 1_000_000,
          "milliard": 1_000_000_000, "milliards": 1_000_000_000}
CURRENCY = {"dinar", "dinars", "algerien", "algeriens", "algerienne", "algeriennes", "da", "dzd",
            "euro", "euros", "dollar", "dollars", "us", "seulement", "montant", "de", "la", "somme"}
CENTS = {"centime", "centimes", "cts", "ct", "cents_monnaie"}


def _norm(s: str) -> list[str]:
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    s = re.sub(r"[-–]", " ", s)
    s = re.sub(r"[^a-z0-9,. ]", " ", s)
    return s.split()


def _words_to_int(tokens: list[str]) -> int | None:
    total, current, seen = 0, 0, False
    prev = None
    for t in tokens:
        if t == "et":
            prev = t
            continue
        if t in ("vingt", "vingts") and prev == "quatre":  # quatre-vingt(s) = 80
            current += 80 - 4
            prev = t
            continue
        prev = t
        if t.isdigit():
            current += int(t)
            seen = True
        elif t in UNITS:
            current += UNITS[t]
            seen = True
        elif t in ("cent", "cents"):
            current = (current or 1) * 100
            seen = True
        elif t in SCALES:
            total += (current or 1) * SCALES[t]
            current = 0
            seen = True
        else:
            return None
    return total + current if seen else None


def lettres_to_number(text) -> float | None:
    if text is None:
        return None
    toks = [t for t in _norm(str(text)) if t not in CURRENCY]
    if not toks:
        return None
    # Séparation partie entière / centimes : « virgule » ou « et NN centimes/cts »
    cents_part: list[str] = []
    if "virgule" in toks:
        i = toks.index("virgule")
        toks, cents_part = toks[:i], toks[i + 1:]
    else:
        idx = [i for i, t in enumerate(toks) if t in CENTS]
        if idx:
            j = idx[0]
            # remonter jusqu'au « et » ou à un chiffre précédant le mot centimes
            k = j - 1
            while k >= 0 and toks[k] != "et" and (toks[k].isdigit() or toks[k] in UNITS
                                                 or toks[k] in ("cent", "cents")):
                k -= 1
            cents_part = toks[k + 1:j]
            toks = toks[:max(k, 0)] if k >= 0 else []
    toks = [t for t in toks if t not in CENTS]
    entier = _words_to_int(toks) if toks else 0
    if entier is None:
        return None
    cents = 0
    if cents_part:
        cents = _words_to_int([t for t in cents_part if t not in CENTS])
        if cents is None or cents >= 100:
            return None
    return round(entier + cents / 100.0, 2)
