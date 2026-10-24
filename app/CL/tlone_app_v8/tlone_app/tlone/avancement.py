"""Avancement d'une lecture par l'IA (barre de progression de l'App).

Aucun échange avec le notebook : on compte les fichiers. Chaque PDF lu produit un JSON (reprise des notebooks :
un PDF qui a déjà son JSON n'est pas relu). Pendant un run :
  lus      = JSON écrits depuis le lancement,
  restants = PDF du dossier d'entrée encore sans JSON (bornés par « Limiter à N »),
  en cours = premier PDF restant (les notebooks traitent les PDF dans l'ordre alphabétique).
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

ETAPES_LECTURE = ("dom_extract", "ov_extract")


def _json_dir_ov(s) -> list[Path]:
    """Dossier JSON du notebook OV configuré (json_dossiers, json_dossiers_v28, _v29…)."""
    out = s.paths.tr_out
    nom = None
    try:
        nb = Path(s.notebooks["ov_extract"]).read_text(encoding="utf-8")
        m = re.search(r'JSON_DIR\s*=\s*OUTPUT_DIR\s*/\s*\\?["\']([^"\'\\]+)', nb)
        nom = m.group(1) if m else None
    except (OSError, KeyError):
        pass
    if nom:
        return [out / nom]
    return sorted(out.glob("json_dossiers*")) if out.exists() else []


def dossiers(s, step: str) -> tuple[Path, list[Path]]:
    if step == "dom_extract":
        return s.paths.dom_in, [s.paths.raw_json_dir]
    return s.paths.tr_in, _json_dir_ov(s)


def _pdfs(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted((p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"),
                  key=lambda p: p.name)


def _jsons(dirs: list[Path]) -> list[Path]:
    return [p for d in dirs if d.exists() for p in d.glob("*.json")]


def _lu(pdf: Path, noms_json: set[str], step: str) -> bool:
    st = pdf.stem.lower()
    if step == "ov_extract":
        return st in noms_json
    return st in noms_json or any(st in n for n in noms_json)


def a_lire(s, step: str) -> list[Path]:
    """PDF déposés et pas encore lus par l'IA."""
    entree, dirs = dossiers(s, step)
    noms = {p.stem.lower() for p in _jsons(dirs)}
    return [p for p in _pdfs(entree) if not _lu(p, noms, step)]


def etat(s, run: dict, now: float | None = None) -> dict:
    """État d'un run de lecture : lus, total, en cours, temps restant estimé (secondes)."""
    now = now or time.time()
    step = run.get("step")
    try:
        t0 = datetime.fromisoformat(run["launched_at"]).timestamp()
    except (KeyError, ValueError, TypeError):
        t0 = now
    _entree, dirs = dossiers(s, step)
    nouveaux = [p for p in _jsons(dirs) if p.stat().st_mtime >= t0]   # launched_at est tronqué à la seconde
    restants = a_lire(s, step)
    lus = len(nouveaux)
    total = lus + len(restants)
    if run.get("max_items"):
        total = min(total, int(run["max_items"]))
    total = max(total, lus)
    debut = [p.stat().st_mtime for p in nouveaux]
    eta = None
    if lus and total > lus:
        ecoule = max(now - min(min(debut), t0), 1.0) if debut else now - t0
        eta = ecoule / lus * (total - lus)
    return {"lus": lus, "total": total, "en_cours": restants[0].stem if restants and lus < total else None,
            "eta_s": eta, "ecoule_s": max(now - t0, 0)}


def duree(sec: float | None) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    if sec < 60:
        return "moins d'une minute"
    m = round(sec / 60)
    return f"environ {m} min" if m < 60 else f"environ {m // 60} h {m % 60:02d}"
