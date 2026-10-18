"""Point d'entrée des Domino Jobs (et du mode local).

    python run_step.py dom_extract --max 10
    python run_step.py dom_post
    python run_step.py ov_extract --run-id ov_extract_20261016_1200
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STEP_NAMES = ("dom_extract", "dom_post", "ov_extract")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=sorted(STEP_NAMES))
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--max", type=int, default=None, help="limite de dossiers (test)")
    ap.add_argument("--data-root", default=None,
                    help="racine des données transmise par l'app (le job écrit au même endroit que l'app)")
    a = ap.parse_args()
    if a.data_root:
        os.environ["TLONE_DATA_ROOT"] = a.data_root
    from tlone import nbrunner  # noqa: E402  (après TLONE_DATA_ROOT)
    sys.exit(nbrunner.run(a.step, run_id=a.run_id, max_items=a.max))
