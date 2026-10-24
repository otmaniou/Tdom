"""Référentiels mensuels transmis par l'employeur : base RH, ATF (attestation fiscale collective),
autorisations ministérielles. Un fichier par mois, tous conservés ; le plus récent fait foi pour un mois."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import rh as _rh
from . import transfers

KINDS = {
    "rh": {"label": "Base RH", "dir": "base_rh", "types": ["xlsx", "xls"],
           "aide": "Fichier RH mensuel (une ligne par salarié et par PART). Référence des documents imprimés."},
    "atf": {"label": "ATF", "dir": "atf", "types": ["xlsx", "xls", "csv"],
            "aide": "Liste collective déclarée au fisc : matricule, nom, salaire net, IRG, montant transférable, période."},
    "aut": {"label": "Autorisations", "dir": "autorisations", "types": ["xlsx", "xls", "csv", "html", "htm"],
            "aide": "Liste ministérielle : travailleur, montant autorisé, période, date de validation / limite. "
                    "HTML accepté s'il contient le tableau (page enregistrée complète)."},
}


def folder(P, kind: str) -> Path:
    return P.referentiels_dir / KINDS[kind]["dir"]


def files(P, kind: str) -> list[Path]:
    d = folder(P, kind)
    out = sorted((p for p in d.iterdir() if p.is_file() and not p.name.startswith(("~$", ".")) and p.suffix != ".json"),
                 key=lambda p: p.stat().st_mtime) if d.exists() else []
    legacy = {"atf": P.atf_xlsx, "aut": P.autorisations_xlsx}.get(kind)
    if legacy is not None and legacy.exists():
        out = [legacy] + out
    return out


def signature(P) -> tuple:
    return tuple((str(p), p.stat().st_mtime) for k in KINDS for p in files(P, k))


def save(P, kind: str, name: str, data: bytes) -> Path:
    d = folder(P, kind)
    d.mkdir(parents=True, exist_ok=True)
    p = d / Path(name).name
    p.write_bytes(data)
    return p


def load_rh(P) -> pd.DataFrame:
    return _rh.load_all(P)


def _load_ref(P, kind: str, columns: list[str], rh: pd.DataFrame | None) -> tuple[pd.DataFrame, list[str]]:
    frames, errs = [], []
    for p in files(P, kind):
        try:
            df = transfers.load_referential(p, columns, rh)
            df["_SOURCE"] = p.name
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{p.name} : {exc}")
    if not frames:
        return pd.DataFrame(columns=columns + ["_MOIS", "_COMPTE", "_SOURCE"]), errs
    df = pd.concat(frames, ignore_index=True)
    last = df.groupby("_MOIS")["_SOURCE"].last().to_dict()
    return df[[last.get(m) == s or pd.isna(m) for m, s in zip(df["_MOIS"], df["_SOURCE"])]].reset_index(drop=True), errs


def load_atf(P, rh: pd.DataFrame | None = None) -> pd.DataFrame:
    return _load_ref(P, "atf", transfers.ATF_COLUMNS, rh)[0]


def load_aut(P, rh: pd.DataFrame | None = None) -> pd.DataFrame:
    return _load_ref(P, "aut", transfers.AUT_COLUMNS, rh)[0]


_MEMO: dict = {}


def load_all(P) -> dict:
    """Base RH + ATF + autorisations ; gardés en mémoire tant que les fichiers ne changent pas (signature) :
    l'Accueil, la page OV, les fichiers BOCI et la régularisation ne relisent pas 10 000+ lignes à chaque clic."""
    key = (str(P.data_root), signature(P))
    hit = _MEMO.get(str(P.data_root))
    if hit and hit[0] == key:
        R = hit[1]
    else:
        rh = load_rh(P)
        atf, e1 = _load_ref(P, "atf", transfers.ATF_COLUMNS, rh)
        aut, e2 = _load_ref(P, "aut", transfers.AUT_COLUMNS, rh)
        R = {"rh": rh, "atf": atf, "aut": aut, "errors": e1 + e2}
        _MEMO[str(P.data_root)] = (key, R)
    return {k: (v.copy() if isinstance(v, pd.DataFrame) else list(v)) for k, v in R.items()}


_DQ: dict = {}


def dq_rh(P, rhdf: pd.DataFrame) -> pd.DataFrame:
    """Contrôles qualité de la base RH, calculés une fois par version des fichiers."""
    key = (str(P.data_root), signature(P))
    hit = _DQ.get(str(P.data_root))
    if not hit or hit[0] != key:
        hit = (key, _rh.dq(rhdf))
        _DQ[str(P.data_root)] = hit
    return hit[1].copy()


def summary(P) -> pd.DataFrame:
    rows = []
    for k, m in KINDS.items():
        fs = files(P, k)
        rows.append({"Référentiel": m["label"], "Fichiers": len(fs), "Dernier fichier": fs[-1].name if fs else "— absent"})
    return pd.DataFrame(rows)
