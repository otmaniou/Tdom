"""Point d'entrée des Domino Jobs (et du mode local).

    python run_step.py dom_extract --max 10
    python run_step.py dom_post
    python run_step.py ov_extract --run-id ov_extract_20261016_1200
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tlone import nbrunner  # noqa: E402
from tlone.config import STEPS  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=sorted(STEPS))
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--max", type=int, default=None, help="limite de dossiers (test)")
    a = ap.parse_args()
    sys.exit(nbrunner.run(a.step, run_id=a.run_id, max_items=a.max))
