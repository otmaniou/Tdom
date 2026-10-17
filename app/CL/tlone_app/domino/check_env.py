"""Vérifie l'environnement TL-One sur Domino (à lancer en Job ou dans un workspace) :

    python /mnt/tlone_app/domino/check_env.py

Contrôle les 3 interpréteurs : versions, classes de modèles attendues, GPU, accès aux modèles
du ModelHub. N'utilise aucune donnée client.
"""
import os
import subprocess
import sys

PROBE = r'''
import importlib, json, sys
r = {"python": sys.executable}
for m in ("streamlit", "pandas", "openpyxl", "pymupdf", "nbclient", "ipykernel", "torch", "transformers"):
    try:
        mod = importlib.import_module(m); r[m] = getattr(mod, "__version__", "ok")
    except Exception as e:
        r[m] = None
try:
    import torch; r["cuda"] = torch.cuda.is_available()
    r["gpu"] = torch.cuda.get_device_name(0) if r["cuda"] else None
except Exception:
    r["cuda"] = None
try:
    import transformers as t
    r["AutoModelForImageTextToText"] = hasattr(t, "AutoModelForImageTextToText")
    r["AutoModelForVision2Seq"] = hasattr(t, "AutoModelForVision2Seq")
except Exception:
    pass
print(json.dumps(r))
'''

TARGETS = {
    "APP + Partie 2": (os.environ.get("TLONE_DOM_POST_PYTHON") or sys.executable,
                       ["streamlit", "pandas", "openpyxl", "pymupdf", "nbclient", "ipykernel"]),
    "Partie 1 (Qwen3.8)": (os.environ.get("TLONE_DOM_EXTRACT_PYTHON", "/opt/venv-tf5/bin/python"),
                           ["torch", "transformers", "pymupdf", "nbclient", "ipykernel", "AutoModelForImageTextToText"]),
    "v26 OV (Qwen2.5-VL)": (os.environ.get("TLONE_OV_EXTRACT_PYTHON", "/opt/venv-tf4/bin/python"),
                            ["torch", "transformers", "pymupdf", "nbclient", "ipykernel", "AutoModelForVision2Seq"]),
}
MODELS = {
    "Qwen3.8-27B-FP8": "/domino/edv/modelhub/ModelHub-model-huggingface-Qwen/Qwen3.8-27B-FP8/main",
    "Qwen2.5-VL-7B": "/domino/edv/modelhub/ModelHub-model-huggingface-Qwen/Qwen2.5-VL-7B-Instruct/main",
}

import json  # noqa: E402

ok_all = True
for label, (py, need) in TARGETS.items():
    print(f"\n== {label} : {py}")
    try:
        out = subprocess.run([py, "-c", PROBE], capture_output=True, text=True, timeout=300)
        r = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception as exc:
        print("   ❌ interpréteur inutilisable :", exc)
        ok_all = False
        continue
    for k in need:
        good = bool(r.get(k))
        ok_all &= good
        print(f"   {'✅' if good else '❌'} {k:30s} {r.get(k)}")
    if "transformers" in need:
        print(f"   ℹ️  CUDA={r.get('cuda')} GPU={r.get('gpu')}")

print("\n== Modèles ModelHub")
for name, path in {**MODELS, **{k: v for k, v in (("TLONE_MODEL_DOM", os.environ.get("TLONE_MODEL_DOM")),
                                                    ("TLONE_MODEL_OV", os.environ.get("TLONE_MODEL_OV"))) if v}}.items():
    print(f"   {'✅' if os.path.isdir(path) else '❌'} {name:18s} {path}")

root = os.environ.get("TLONE_DATA_ROOT", "/mnt/data")
w = os.access(root, os.W_OK) if os.path.isdir(root) else False
print(f"\n== Données : {root} -> {'✅ accessible en écriture' if w else '❌ absent ou lecture seule'}")
print("\nRÉSULTAT :", "✅ environnement prêt" if ok_all else "❌ corriger les lignes en rouge")
sys.exit(0 if ok_all else 1)
