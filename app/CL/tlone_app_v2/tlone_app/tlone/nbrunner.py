"""Exécution des notebooks validés, sans les modifier sur disque.

Le notebook source reste la référence qualité (baseline). Le runner applique à
une COPIE en mémoire uniquement des patchs de configuration :
  * racine des données (/mnt/data -> TLONE_DATA_ROOT) si elle diffère ;
  * limite de dossiers (MAX_PDFS / MAX_DOSSIERS) pour les tests ;
  * chemin du modèle si TLONE_MODEL_* est renseigné ;
  * glob '*.pdf' rendu insensible à la casse (les spécimens sont en .PDF).
Le notebook exécuté (avec ses sorties) est archivé dans runs/ pour audit.
"""
from __future__ import annotations

import json
import re
import traceback
from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = "/mnt/data"

_GLOB_PATTERNS = [
    # Partie 1
    ("sorted(INPUT_DIR.glob('*.pdf'))",
     "sorted(p for p in (INPUT_DIR.iterdir() if INPUT_DIR.exists() else []) if p.is_file() and p.suffix.lower() == '.pdf')"),
    # v26 transferts
    ('sorted(INPUT_DIR.glob("*.pdf"))',
     "sorted(p for p in (INPUT_DIR.iterdir() if INPUT_DIR.exists() else []) if p.is_file() and p.suffix.lower() == '.pdf')"),
]


_RIB_KO = "02700731010910800156"   # siège 07310109108, ordinal 001, clé lue 56, attendue 91
_RIB_OK = "02700731010910800094"   # clé 94 valide (Modulo 97)
_SELFTEST_PATTERNS = [
    ("extract_siege_racine('ACCOUNT_EXAMPLE')", f"extract_siege_racine('{_RIB_KO}')"),
    ("_test_compte = analyze_dom_compte_local('ACCOUNT_EXAMPLE')", f"_test_compte = analyze_dom_compte_local('{_RIB_KO}')"),
    ("_test_rib_ok = analyze_dom_compte_local('ACCOUNT_EXAMPLE')", f"_test_rib_ok = analyze_dom_compte_local('{_RIB_OK}')"),
]


def patch_source(src: str, step: str, data_root: str, max_items: int | None,
                 model_path: str | None) -> tuple[str, list[str]]:
    """Retourne (source patchée, liste des patchs appliqués)."""
    applied: list[str] = []
    if data_root and data_root.rstrip("/") != DEFAULT_ROOT:
        n = src.count(DEFAULT_ROOT)
        if n:
            src = src.replace(DEFAULT_ROOT, data_root.rstrip("/"))
            applied.append(f"DATA_ROOT x{n}")

    # Partie 2 : l'autotest V5.3 contient un compte anonymisé ('ACCOUNT_EXAMPLE') qui fait
    # échouer ses propres assert. On le remplace par des RIB synthétiques qui reproduisent
    # exactement les valeurs attendues (reste 62 / clé 91 ; clé 94 valide).
    for old, new in _SELFTEST_PATTERNS:
        if old in src:
            src = src.replace(old, new)
            if "SELFTEST_SYNTHETIC_RIB" not in applied:
                applied.append("SELFTEST_SYNTHETIC_RIB")

    for old, new in _GLOB_PATTERNS:
        if old in src:
            src = src.replace(old, new)
            applied.append("GLOB_PDF_CASE_INSENSITIVE")

    if max_items:
        for var in ("MAX_PDFS", "MAX_DOSSIERS"):
            pat = re.compile(rf"^({var}\s*=\s*)None", re.M)
            if pat.search(src):
                src = pat.sub(rf"\g<1>{int(max_items)}", src)
                applied.append(f"{var}={int(max_items)}")
        if step == "ov_extract" and "pdfs = sorted(" in src and "MAX_PDFS" not in src:
            src = re.sub(r"^(pdfs = sorted\(.*\))\s*$", rf"\1[:{int(max_items)}]", src, flags=re.M)
            applied.append(f"pdfs[:{int(max_items)}]")

    if model_path:
        pat = re.compile(r"^(MODEL_PATH\s*=\s*)(['\"]).*?\2", re.M)
        if pat.search(src):
            src = pat.sub(lambda m: f"{m.group(1)}{json.dumps(model_path)}", src)
            applied.append("MODEL_PATH")
    return src, applied


def prepare_notebook(nb_path: Path, step: str, data_root: str, max_items: int | None,
                     model_path: str | None):
    import nbformat
    nb = nbformat.read(str(nb_path), as_version=4)
    all_applied: list[str] = []
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        new, applied = patch_source(cell.source, step, data_root, max_items, model_path)
        cell.source = new
        all_applied.extend(applied)
    return nb, all_applied


def ensure_kernel() -> str:
    """Noyau Jupyter lié à l'interpréteur courant.

    Indispensable quand un même environnement contient deux venvs (transformers 4 / 5) :
    le noyau « python3 » par défaut pourrait pointer vers un autre Python.
    """
    import hashlib
    import sys
    name = "tlone-" + hashlib.sha1(sys.executable.encode()).hexdigest()[:8]
    try:
        from jupyter_client.kernelspec import KernelSpecManager
        if name not in KernelSpecManager().find_kernel_specs():
            from ipykernel.kernelspec import install
            install(user=True, kernel_name=name, display_name=f"TL-One ({sys.executable})")
        return name
    except Exception as exc:  # noqa: BLE001
        print(f"[TL-One] noyau dédié impossible ({exc!r}) -> python3", flush=True)
        return "python3"


def _write_status(status_path: Path, **kw) -> None:
    data = {}
    if status_path.exists():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(kw)
    status_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def run(step: str, run_id: str | None = None, max_items: int | None = None,
        timeout_cell: int = 6 * 3600) -> int:
    from nbclient import NotebookClient

    from .config import load_settings

    s = load_settings()
    s.paths.ensure()  # crée domiciliations_in, transferts_in... si absents (racine vierge)
    nb_path = s.notebooks[step]
    run_id = run_id or f"{step}_{datetime.now():%Y%m%d_%H%M%S}"
    s.paths.runs_dir.mkdir(parents=True, exist_ok=True)
    status_path = s.paths.runs_dir / f"{run_id}.status.json"
    out_nb = s.paths.runs_dir / f"{run_id}.executed.ipynb"

    model = s.model_dom if step == "dom_extract" else s.model_ov if step == "ov_extract" else None
    nb, applied = prepare_notebook(nb_path, step, str(s.paths.data_root), max_items, model or None)
    _write_status(status_path, run_id=run_id, step=step, status="RUNNING",
                  started_at=datetime.now().isoformat(timespec="seconds"),
                  notebook=nb_path.name, patches=applied, max_items=max_items)
    print(f"[TL-One] {run_id} | {nb_path.name} | patchs={applied}", flush=True)

    import sys
    kernel = ensure_kernel()
    _write_status(status_path, python=sys.executable, kernel=kernel)
    client = NotebookClient(nb, timeout=timeout_cell, kernel_name=kernel,
                            resources={"metadata": {"path": str(s.paths.data_root)}})
    rc = 0
    try:
        client.execute()
        _write_status(status_path, status="SUCCEEDED")
    except Exception as exc:  # noqa: BLE001
        rc = 1
        _write_status(status_path, status="FAILED", error=repr(exc)[:4000],
                      traceback=traceback.format_exc()[-6000:])
        print(f"[TL-One] ÉCHEC {run_id}: {exc!r}", flush=True)
    finally:
        import nbformat
        try:
            nbformat.write(nb, str(out_nb))
        except Exception:
            pass
        _write_status(status_path, finished_at=datetime.now().isoformat(timespec="seconds"),
                      executed_notebook=str(out_nb))
    return rc
