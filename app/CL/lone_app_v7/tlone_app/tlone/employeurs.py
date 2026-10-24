"""Registre des employeurs (multi-employeur).

Chaque employeur a son propre dossier de données <home>/employeurs/<CODE>/ (mêmes sous-dossiers que
l'app mono-employeur : domiciliations_in, transferts_in, referentiels, document_pipeline/…) et une ligne
dans <home>/_commun/employeurs.csv. Création : raison sociale + NIF (obligatoires).
Le dossier existant pointé par TLONE_DATA_ROOT (ex. …/employeurs/TOSYALI) est inscrit automatiquement.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

COLUMNS = ["CODE", "RAISON_SOCIALE", "NIF", "MOTS_CLES", "AGENCE", "DATE_CREATION", "CREE_PAR", "ACTIF", "DEMO"]
_STOP = {"SPA", "SARL", "EURL", "SNC", "SA", "ALGERIE", "ALGERIA", "INDUSTRY", "INDUSTRIE", "IRON", "STEEL", "SOCIETE",
         "COMPANY", "GROUP", "GROUPE", "DE", "DU", "LA", "LE", "LES", "ET", "AND", "THE", "DES", "EL", "DEMO"}


def registry_path(home: Path) -> Path:
    return Path(home) / "_commun" / "employeurs.csv"


def employeurs_dir(home: Path) -> Path:
    return Path(home) / "employeurs"


def _up(v) -> str:
    s = unicodedata.normalize("NFKD", str(v or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


def mot_cle(raison: str) -> str:
    """Mot distinctif de la raison sociale (contrôle « l'employeur lu contient le mot-clé »)."""
    mots = [m for m in re.split(r"[^A-Z0-9]+", _up(raison)) if len(m) >= 3 and m not in _STOP]
    return mots[0] if mots else _up(raison)[:12]


def code_for(raison: str, existing: set[str]) -> str:
    base = re.sub(r"[^A-Z0-9]+", "_", mot_cle(raison)).strip("_")[:20] or "EMPLOYEUR"
    code, i = base, 2
    while code in existing:
        code, i = f"{base}_{i}", i + 1
    return code


def nif_ok(nif: str) -> tuple[bool, str]:
    d = re.sub(r"\D", "", str(nif or ""))
    if not d:
        return False, "NIF obligatoire"
    if len(d) not in (15, 20):
        return True, f"NIF de {len(d)} chiffres (attendu : 15 ou 20) — à vérifier"
    return True, ""


def load(home: Path) -> pd.DataFrame:
    p = registry_path(home)
    if not p.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(p, dtype=str, encoding="utf-8-sig").reindex(columns=COLUMNS).fillna("")


def _save(home: Path, df: pd.DataFrame) -> None:
    p = registry_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.reindex(columns=COLUMNS).to_csv(p, index=False, encoding="utf-8-sig")


def get(home: Path, code: str) -> dict | None:
    df = load(home)
    m = df[df["CODE"] == code]
    return m.iloc[0].to_dict() if not m.empty else None


def ensure_registered(home: Path, code: str | None, raison_defaut: str = "") -> None:
    """Inscrit les dossiers d'employeurs déjà présents (ex. TOSYALI) sans les modifier."""
    df = load(home)
    known = set(df["CODE"])
    rows = []
    d = employeurs_dir(home)
    present = [p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))] if d.exists() else []
    for c in dict.fromkeys(([code] if code else []) + present):
        if c and c not in known:
            rs = raison_defaut if c == code and raison_defaut else c
            rows.append({"CODE": c, "RAISON_SOCIALE": rs, "NIF": "", "MOTS_CLES": mot_cle(rs) if rs != c else c,
                         "AGENCE": "", "DATE_CREATION": datetime.now().isoformat(timespec="seconds"),
                         "CREE_PAR": "inscription automatique", "ACTIF": "OUI", "DEMO": ""})
    if rows:
        try:
            _save(home, pd.concat([df, pd.DataFrame(rows)], ignore_index=True))
        except OSError:
            pass


def create(home: Path, raison: str, nif: str, user: str, mots_cles: str = "", agence: str = "",
           demo: bool = False, code: str | None = None) -> dict:
    raison = re.sub(r"\s+", " ", str(raison or "")).strip()
    if not raison:
        raise ValueError("Raison sociale obligatoire")
    ok, msg = nif_ok(nif)
    if not ok:
        raise ValueError(msg)
    df = load(home)
    nif_d = re.sub(r"\D", "", nif)
    if not demo and nif_d and (df["NIF"].map(lambda x: re.sub(r"\D", "", x)) == nif_d).any():
        raise ValueError(f"NIF {nif} déjà enregistré pour {df[df['NIF'].map(lambda x: re.sub(r'[^0-9]', '', x)) == nif_d]['RAISON_SOCIALE'].iloc[0]}")
    code = code or code_for(raison, set(df["CODE"]) | {p.name for p in employeurs_dir(home).glob("*")})
    row = {"CODE": code, "RAISON_SOCIALE": raison.upper(), "NIF": nif_d, "MOTS_CLES": mots_cles or mot_cle(raison),
           "AGENCE": agence, "DATE_CREATION": datetime.now().isoformat(timespec="seconds"), "CREE_PAR": user,
           "ACTIF": "OUI", "DEMO": "OUI" if demo else ""}
    df = pd.concat([df[df["CODE"] != code], pd.DataFrame([row])], ignore_index=True)
    _save(home, df)
    from .config import Paths
    Paths(employeurs_dir(home) / code).ensure()
    return row


def update(home: Path, code: str, **fields) -> None:
    df = load(home)
    for k, v in fields.items():
        if k in COLUMNS and k != "CODE":
            df.loc[df["CODE"] == code, k] = v
    _save(home, df)


def search(df: pd.DataFrame, q: str) -> pd.DataFrame:
    if not q:
        return df
    k = _up(q)
    return df[df.apply(lambda r: k in _up(r["RAISON_SOCIALE"]) or k in str(r["NIF"]) or k in _up(r["CODE"]), axis=1)]
