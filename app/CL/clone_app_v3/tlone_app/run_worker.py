"""Worker GPU TL-One, à lancer à la main dans un workspace GPU (environnement tlone) :

    /opt/conda/envs/tlone-tf4/bin/python /mnt/code/tlone_app_v2/run_worker.py --prewarm

L'App doit être en TLONE_RUN_MODE=worker. Ctrl+C pour arrêter. Voir tlone/worker.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tlone.worker import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
