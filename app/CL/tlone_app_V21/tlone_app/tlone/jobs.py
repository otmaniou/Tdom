"""Lancement et suivi des traitements lourds.

Mode `domino` : un Domino Job par étape (le tier GPU n'est réservé que pendant
l'extraction ; l'app elle-même tourne sur un petit tier CPU).
Mode `local`  : sous-processus détaché (Mac de dev, machine vast.ai).

L'état de référence d'une exécution est le fichier runs/<run_id>.status.json
écrit par le runner ; le statut Domino n'est qu'un complément.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import APP_DIR, STEPS, Settings


def _jobs_index(s: Settings) -> Path:
    return s.paths.runs_dir / "jobs.jsonl"


def _append_index(s: Settings, rec: dict) -> None:
    s.paths.runs_dir.mkdir(parents=True, exist_ok=True)
    with _jobs_index(s).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _domino_request(method: str, path: str, payload: dict | None = None, timeout: int = 60) -> dict:
    import requests

    proxy = os.environ.get("DOMINO_API_PROXY")
    if proxy:  # Domino >= 5.x : jeton injecté par le proxy local
        base, headers = proxy.rstrip("/"), {}
    else:
        base = os.environ["DOMINO_API_HOST"].rstrip("/")
        headers = {"X-Domino-Api-Key": os.environ["DOMINO_USER_API_KEY"]}
    r = requests.request(method, base + path, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json() if r.content else {}


def _job_cmd(prefix: str, python: str) -> str:
    """Remplace l'interpréteur de TLONE_JOB_CMD par celui de l'étape (venv tf4 / tf5)."""
    parts = shlex.split(prefix)
    if python and parts and Path(parts[0]).name.startswith("python"):
        parts[0] = python
    return " ".join(shlex.quote(x) for x in parts)


def launch(s: Settings, step: str, max_items: int | None = None, user: str | None = None) -> dict:
    if step not in STEPS:
        raise ValueError(step)
    from . import preflight
    ko = preflight.blocking(preflight.check_step(s, step))
    if ko:  # garde-fou : même si l'interface est contournée, aucun job ne part sans ses prérequis
        raise RuntimeError("prérequis bloquants : " + " · ".join(f"{r['contrôle']} = {r['valeur']}" for r in ko))
    run_id = f"{step}_{datetime.now():%Y%m%d_%H%M%S}"
    args = (f"{step} --run-id {run_id} --data-root {shlex.quote(str(s.paths.data_root))}"
            + (f" --max {int(max_items)}" if max_items else ""))
    rec = {"run_id": run_id, "step": step, "mode": s.run_mode, "max_items": max_items,
           "user": user, "launched_at": datetime.now().isoformat(timespec="seconds")}

    if step == "dom_post" and s.paths.validation_xlsx.exists():
        # La Partie 2 réécrit le classeur : on garde les décisions déjà saisies (report possible).
        from .common import backup
        rec["backup_validation"] = str(backup(s.paths.validation_xlsx))

    if s.run_mode == "worker":
        # démonstration / production : un worker GPU déjà lancé (run_worker.py) prend la demande
        from .worker import enqueue
        rec["queue_file"] = str(enqueue(s, dict(rec)))
    elif s.run_mode == "domino":
        rt = s.step_runtime(step)
        tier = rt["tier"]
        payload = {"projectId": os.environ["DOMINO_PROJECT_ID"],
                   "commandToRun": f"{_job_cmd(s.job_cmd_prefix, s.step_runtime(step)['python'])} {args}",
                   "title": f"TL-One {STEPS[step]['label']}"}
        if tier:
            payload["overrideHardwareTierId"] = tier
        if rt["environment"]:
            # Partie 1 (Qwen3.8, transformers 5) et v26 (Qwen2.5-VL, transformers 4) : environnements distincts
            payload["environmentId"] = rt["environment"]
            rec["environment"] = rt["environment"]
        resp = _domino_request("POST", "/v4/jobs/start", payload)
        rec["domino_job_id"] = resp.get("id") or resp.get("jobId")
        rec["hardware_tier"] = tier or "(défaut projet)"
    else:
        s.paths.runs_dir.mkdir(parents=True, exist_ok=True)
        log = s.paths.runs_dir / f"{run_id}.log"
        # Mode local (vast.ai) : un venv par modèle possible via TLONE_<ETAPE>_PYTHON
        py = s.step_runtime(step)["python"] or sys.executable  # défaut : env conda de l'étape (config)
        rec["python"] = py
        cmd = [py, str(APP_DIR / "run_step.py")] + shlex.split(args)
        with log.open("w", encoding="utf-8") as fh:
            p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=str(APP_DIR),
                                 start_new_session=True, env=os.environ.copy())
        rec["pid"] = p.pid
        rec["log"] = str(log)
    _append_index(s, rec)
    return rec


def domino_status(job_id: str) -> str | None:
    try:
        d = _domino_request("GET", f"/v4/jobs/{job_id}", timeout=5)
        st = d.get("statuses") or {}
        return st.get("executionStatus") or d.get("status")
    except Exception:
        return None


def list_runs(s: Settings, limit: int = 30) -> list[dict]:
    idx = _jobs_index(s)
    recs: list[dict] = []
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    recs = recs[-limit:][::-1]
    for r in recs:
        sp = s.paths.runs_dir / f"{r['run_id']}.status.json"
        if sp.exists():
            try:
                st = json.loads(sp.read_text(encoding="utf-8"))
                r.update({k: st.get(k) for k in ("status", "finished_at", "error", "patches", "executed_notebook")})
            except Exception:
                pass
        else:
            r["status"] = "EN_FILE"  # job pas encore démarré (pull d'image, attente GPU...)
    return recs


def mark_abandoned(s: Settings, run_id: str, user: str | None = None) -> None:
    """Clôt un run resté EN_FILE / RUNNING (job arrêté dans Domino, conteneur redémarré...)."""
    sp = s.paths.runs_dir / f"{run_id}.status.json"
    st = {}
    if sp.exists():
        try:
            st = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            st = {}
    st.update({"run_id": run_id, "status": "ABANDONNE", "finished_at": datetime.now().isoformat(timespec="seconds"),
               "error": f"marqué abandonné par {user or '?'}"})
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def last_success(s: Settings, step: str) -> dict | None:
    for r in list_runs(s, limit=500):
        if r.get("step") == step and r.get("status") == "SUCCEEDED":
            return r
    return None
