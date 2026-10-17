"""Contrôle de démarrage TL-One : vérifie TOUS les prérequis avant d'ouvrir l'app
ou de lancer un traitement. Aucun paquet n'est installé, rien n'est modifié.

    python -m tlone.preflight            # rapport complet (workspace, logs de l'App)
    python -m tlone.preflight dom_extract  # prérequis d'une étape

Niveaux : OK · ATTENTION (l'app marche, mais à corriger) · BLOQUANT (lancement interdit).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .config import APP_DIR, NOTEBOOK_DIR, STEPS, Settings, load_settings

OK, WARN, KO = "OK", "ATTENTION", "BLOQUANT"

# Bibliothèques exigées par interpréteur (l'image Docker doit les contenir).
APP_MODULES = ["streamlit", "pandas", "openpyxl", "fitz", "requests", "nbclient", "nbformat", "ipykernel"]
STEP_MODULES = {
    "dom_extract": ["torch", "transformers", "fitz", "pandas", "nbclient", "nbformat", "ipykernel"],
    "dom_post": ["pandas", "openpyxl", "nbclient", "nbformat", "ipykernel"],
    "ov_extract": ["torch", "transformers", "fitz", "pandas", "openpyxl", "nbclient", "nbformat", "ipykernel"],
}
# Version de transformers attendue par étape (préfixe).
TRANSFORMERS_PREFIX = {"dom_extract": "5.", "ov_extract": "4.57"}
MODEL_DEFAULT = {
    "dom_extract": "/domino/edv/modelhub/ModelHub-model-huggingface-Qwen/Qwen3.8-27B-FP8/main",
    "ov_extract": "/domino/edv/modelhub/ModelHub-model-huggingface-Qwen/Qwen2.5-VL-7B-Instruct/main",
}
CARTHAGO_CLIENT = ["Client"]
CARTHAGO_NAME = ["Nom complet/Raison sociale"]
PENDING_MAX_AGE = timedelta(hours=3)

_PROBE = r'''
import importlib, json, sys
mods = json.loads(sys.argv[1]); r = {"python": sys.version.split()[0]}
for m in mods:
    try:
        mod = importlib.import_module(m); r[m] = str(getattr(mod, "__version__", "ok"))
    except Exception:
        r[m] = None
if "torch" in mods and r.get("torch"):
    import torch; r["cuda"] = bool(torch.cuda.is_available())
print(json.dumps(r))
'''


def _row(level, item, value="", hint=""):
    return {"niveau": level, "contrôle": item, "valeur": str(value), "action": hint}


def _key(v) -> str:
    s = unicodedata.normalize("NFKD", str(v))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", s)).strip()


def probe_python(py: str, modules: list[str]) -> dict | None:
    """Importe les modules dans l'interpréteur `py` (sous-processus) ; None si inutilisable.
    Résultat mis en cache pour la durée du processus (l'image ne change pas en cours de route)."""
    return _probe_cached(py, tuple(modules))


@lru_cache(maxsize=32)
def _probe_cached(py: str, modules: tuple) -> dict | None:
    try:
        out = subprocess.run([py, "-c", _PROBE, json.dumps(list(modules))], capture_output=True,
                             text=True, timeout=180)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def count_pdfs(folder: Path) -> int:
    return sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf") if folder.is_dir() else 0


def step_input(s: Settings, step: str) -> tuple[str, Path, int]:
    P = s.paths
    if step == "dom_extract":
        return "PDF DOM à traiter", P.dom_in, count_pdfs(P.dom_in)
    if step == "ov_extract":
        return "PDF OV à traiter", P.tr_in, count_pdfs(P.tr_in)
    n = len(list(P.raw_json_dir.glob("*.json"))) if P.raw_json_dir.is_dir() else 0
    return "JSON de la Partie 1", P.raw_json_dir, n


def pending_runs(s: Settings, step: str) -> list[dict]:
    from . import jobs
    now = datetime.now()
    out = []
    for r in jobs.list_runs(s, 200):
        if r.get("step") != step or r.get("status") not in ("EN_FILE", "RUNNING"):
            continue
        try:
            if now - datetime.fromisoformat(r["launched_at"]) > PENDING_MAX_AGE:
                continue
        except Exception:
            pass
        out.append(r)
    return out


def check_general(s: Settings) -> list[dict]:
    rows = []
    P = s.paths
    env_root = os.environ.get("TLONE_DATA_ROOT")
    if not env_root:
        rows.append(_row(KO, "TLONE_DATA_ROOT", "non défini → /mnt/data",
                         "Settings du projet > Environment variables : "
                         "TLONE_DATA_ROOT=/mnt/data/document_pipeline/employeurs/TOSYALI"))
    if not P.data_root.is_dir():
        rows.append(_row(KO, "Dossier de données", P.data_root, "Dossier absent : vérifier le dataset monté "
                                                                "(étape Data de l'App / du job)"))
    elif not os.access(P.data_root, os.W_OK):
        rows.append(_row(KO, "Dossier de données", P.data_root, "Lecture seule : le dataset doit être monté en écriture"))
    else:
        rows.append(_row(OK, "Dossier de données", P.data_root))

    for step, nb in s.notebooks.items():
        rows.append(_row(OK if nb.exists() else KO, f"Notebook {step}", nb.name,
                         "" if nb.exists() else f"Copier le notebook dans {NOTEBOOK_DIR}"))

    r = probe_python(sys.executable, APP_MODULES) or {}
    miss = [m for m in APP_MODULES if not r.get(m)]
    rows.append(_row(KO if miss else OK, "Bibliothèques de l'app", sys.executable,
                     f"Manquent dans l'image : {', '.join(miss)} → révision d'environnement" if miss else ""))

    rows.append(_row(OK, "Mode d'exécution", s.run_mode))
    if s.run_mode == "domino":
        if not os.environ.get("DOMINO_PROJECT_ID"):
            rows.append(_row(KO, "DOMINO_PROJECT_ID", "absent", "Mode domino hors Domino : TLONE_RUN_MODE=local"))
        if not (os.environ.get("DOMINO_API_PROXY") or
                (os.environ.get("DOMINO_API_HOST") and os.environ.get("DOMINO_USER_API_KEY"))):
            rows.append(_row(KO, "Accès API Domino", "aucun jeton", "Impossible de lancer des jobs"))

    c = P.carthago_xlsx
    if not c.exists():
        rows.append(_row(WARN, "Export CarthagoDom", c.name, "Absent : la Partie 2 ne fera aucun rapprochement"))
    else:
        rows += check_carthago(c)
    rows.append(_row(OK if P.param_aug_xlsx.exists() else WARN, "Calendrier des augmentations",
                     P.param_aug_xlsx.name, "" if P.param_aug_xlsx.exists() else "Onglet ⑤ Paramètres"))
    return rows


def check_carthago(path: Path) -> list[dict]:
    """Reproduit la détection de colonnes de la Partie 2 (sinon elle échoue)."""
    try:
        import pandas as pd
        cols = set()
        for sh, df in pd.read_excel(path, sheet_name=None, nrows=5, dtype=str).items():
            cols |= {str(c) for c in df.columns}
    except Exception as exc:
        return [_row(KO, "Export CarthagoDom", path.name, f"Illisible : {exc}")]
    keys = {_key(c) for c in cols}
    rows = []
    for label, wanted in (("Colonne Carthago « Client »", CARTHAGO_CLIENT),
                          ("Colonne Carthago « Nom complet/Raison sociale »", CARTHAGO_NAME)):
        found = any(_key(w) in keys for w in wanted)
        rows.append(_row(OK if found else KO, label, "trouvée" if found else "absente",
                         "" if found else "En-têtes lus : " + " | ".join(sorted(cols))[:400]))
    return rows


def check_step(s: Settings, step: str) -> list[dict]:
    rows = []
    rt = s.step_runtime(step)
    label, folder, n = step_input(s, step)
    rows.append(_row(OK if n else KO, label, f"{n} dans {folder}",
                     "" if n else ("Déposer puis cliquer « Copier … »" if step != "dom_post"
                                   else "Lancer d'abord l'extraction DOM (Partie 1)")))
    if step == "dom_post":
        if s.paths.carthago_xlsx.exists():
            rows += [r for r in check_carthago(s.paths.carthago_xlsx) if r["niveau"] != OK]
        else:
            rows.append(_row(KO, "Export CarthagoDom", "absent", "Déposer « Dossier de domiciliation.xlsx »"))

    py = rt["python"]
    if not Path(py).exists():
        rows.append(_row(KO, f"Python {step}", py, f"Interpréteur absent : TLONE_{step.upper()}_PYTHON"))
    else:
        mods = STEP_MODULES[step]
        r = probe_python(py, mods)
        if r is None:
            rows.append(_row(KO, f"Python {step}", py, "Interpréteur inutilisable"))
        else:
            miss = [m for m in mods if not r.get(m)]
            rows.append(_row(KO if miss else OK, f"Bibliothèques {step}", py,
                             f"Manquent : {', '.join(miss)}" if miss else ""))
            want = TRANSFORMERS_PREFIX.get(step)
            if want and r.get("transformers"):
                good = str(r["transformers"]).startswith(want)
                rows.append(_row(OK if good else KO, f"transformers {step}", r["transformers"],
                                 "" if good else f"Attendu {want}x"))

    if STEPS[step]["gpu"]:
        model = rt["model"] or MODEL_DEFAULT[step]
        here = Path(model).is_dir()
        # En mode domino le modèle est lu par le job : absent ici = ModelHub non monté sur l'App (simple alerte).
        lvl = OK if here else (WARN if s.run_mode == "domino" else KO)
        rows.append(_row(lvl, f"Modèle {step}", model,
                         "" if here else "ModelHub non visible ici : vérifier qu'il est monté sur le job"))
        if s.run_mode == "domino":
            rows.append(_row(OK if rt["tier"] else KO, "Tier GPU du job", rt["tier"] or "non défini",
                             "" if rt["tier"] else "Définir TLONE_GPU_TIER (identifiant du tier H100) — "
                                                   "sinon le job part sur le tier par défaut du projet (CPU)"))
    if s.run_mode == "domino":
        rows.append(_row(OK if rt["environment"] else WARN, "Environnement du job",
                         rt["environment"] or "défaut du projet",
                         "" if rt["environment"] else "Vérifier que l'environnement par défaut du projet est « tlone »"
                                                      " (ou définir TLONE_ENV_ID)"))
    pend = pending_runs(s, step)
    if pend:
        rows.append(_row(KO, "Run déjà en cours", ", ".join(r["run_id"] for r in pend),
                         "Attendre la fin, ou l'arrêter dans Jobs puis « Marquer abandonné »"))
    return rows


def blocking(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["niveau"] == KO]


def report(s: Settings | None = None, steps=None) -> list[dict]:
    s = s or load_settings()
    rows = [dict(r, étape="général") for r in check_general(s)]
    for st in steps or list(STEPS):
        rows += [dict(r, étape=st) for r in check_step(s, st)]
    return rows


def main(argv: list[str]) -> int:
    s = load_settings()
    steps = [a for a in argv if a in STEPS] or list(STEPS)
    rows = report(s, steps)
    icon = {OK: "✅", WARN: "⚠️ ", KO: "❌"}
    print(f"[TL-One] Contrôle de démarrage — app {APP_DIR} — données {s.paths.data_root} — mode {s.run_mode}")
    for r in rows:
        line = f"  {icon[r['niveau']]} [{r['étape']}] {r['contrôle']} : {r['valeur']}"
        print(line + (f"  → {r['action']}" if r["action"] else ""))
    n_ko = len(blocking(rows))
    print(f"[TL-One] {'PRÊT' if not n_ko else f'{n_ko} point(s) BLOQUANT(S)'}")
    return 1 if n_ko else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
