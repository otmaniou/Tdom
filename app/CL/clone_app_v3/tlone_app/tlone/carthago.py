"""Colonnes de l'export CarthagoDom : détection tolérante des en-têtes réels.

La Partie 2 attend « Client » et « Nom complet/Raison sociale » (CARTHAGO_*_COL) et cherche le
n° de domiciliation parmi une liste d'alias. L'export réel peut nommer autrement ces colonnes :
l'app détecte la bonne colonne et le runner la transmet au notebook (patch en mémoire), sans
modifier le .ipynb. Surcharge possible : TLONE_CARTHAGO_CLIENT_COL / _NAME_COL / _DOM_REF_COL.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

CLIENT = ["Client", "Code client", "N° client", "Numéro client", "Racine client"]
NAME = ["Nom complet/Raison sociale", "Nom complet / Raison sociale", "Nom complet", "Raison sociale",
        "Nom / Raison sociale", "Nom client", "Name", "Nom"]
# alias du notebook Partie 2 (CARTHAGO_DOM_REF_ALIASES), puis variantes courantes
DOM_REF = ["Numéro de domiciliation", "Numero de domiciliation", "N° domiciliation", "N° de domiciliation",
           "No domiciliation", "Référence domiciliation", "Reference domiciliation", "Réf domiciliation",
           "Ref domiciliation", "Numero DOM", "Numéro DOM", "N° DOM",
           "Numéro domiciliation", "Domiciliation", "Référence DOM", "Reference DOM", "Dom reference"]
AGENCE = ["Agence", "Agence domiciliataire", "Code agence"]
NOTEBOOK_DOM_REF = set(DOM_REF[:12])


def key(v) -> str:
    s = unicodedata.normalize("NFKD", str(v))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", s)).strip()


def read_headers(path: Path) -> list[str]:
    import pandas as pd
    cols: list[str] = []
    for _, df in pd.read_excel(path, sheet_name=None, nrows=0).items():
        for c in df.columns:
            if str(c) not in cols and not str(c).startswith("Unnamed"):
                cols.append(str(c))
    return cols


def _find(headers: list[str], aliases: list[str], prefix: bool = False) -> str | None:
    by_key = {key(h): h for h in headers}
    for a in aliases:
        if key(a) in by_key:
            return by_key[key(a)]
    if prefix:  # ex. « Nom comp… » tronqué ou suffixé
        for a in aliases:
            for k, h in by_key.items():
                if len(key(a)) >= 6 and k.startswith(key(a)[:8]):
                    return h
    return None


def detect(headers: list[str]) -> dict:
    env = {k: os.environ.get(f"TLONE_CARTHAGO_{k.upper()}_COL") for k in ("client", "name", "dom_ref")}
    return {
        "client": env["client"] or _find(headers, CLIENT),
        "name": env["name"] or _find(headers, NAME, prefix=True),
        "dom_ref": env["dom_ref"] or _find(headers, DOM_REF),
        "agence": _find(headers, AGENCE),
        "headers": headers,
    }
