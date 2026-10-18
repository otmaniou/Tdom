"""Worker GPU « à chaud » pour les démonstrations (et plus tard la production).

Lancé à la main dans un workspace GPU (environnement tlone) :

    /opt/conda/envs/tlone-tf4/bin/python /mnt/code/tlone_app_v2/run_worker.py

L'App (TLONE_RUN_MODE=worker) dépose une demande dans runs/queue/ ; le worker la traite et
écrit runs/<run_id>.status.json comme un job : l'App affiche le résultat de la même façon.

Le modèle n'est chargé qu'UNE fois : chaque notebook GPU tourne dans un noyau Jupyter qui reste
ouvert (un par interpréteur : tlone-tf5 pour la Partie 1, tlone-tf4 pour la v26). À chaque demande,
seules la cellule de configuration (liste des PDF, limite N) et la ou les cellules de traitement
sont ré-exécutées. Les .ipynb ne sont PAS modifiés : mêmes patchs en mémoire que nbrunner.
La Partie 2 (CPU, sans modèle) est exécutée à froid, comme un job.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import nbrunner
from .config import APP_DIR, Settings, load_settings

GPU_STEPS = ("dom_extract", "ov_extract")
# Cellules ré-exécutées à chaque demande (repérées par leur contenu, pas par leur numéro).
CONFIG_MARKER = "pdfs = sorted("
MODEL_MARKER = "from_pretrained"
PROCESS_MARKERS = {
    "dom_extract": ("if not pdfs:",),
    "ov_extract": ("for pdf_path in pdfs", "pd.read_excel(EXCEL_PATH"),
}
HEARTBEAT_MAX_AGE_S = 90


def queue_dir(s: Settings) -> Path:
    return s.paths.runs_dir / "queue"


def heartbeat_path(s: Settings) -> Path:
    return s.paths.runs_dir / "worker_heartbeat.json"


def worker_signal(s: Settings) -> dict | None:
    """Dernier battement du worker, même ancien (None si jamais démarré ici) ; age_s en secondes.
    L'âge vient de l'horloge epoch (indépendante du fuseau horaire de l'App et du workspace)."""
    p = heartbeat_path(s)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if "epoch" in d:
            age = time.time() - float(d["epoch"])
        else:  # ancien format : heure locale du workspace
            age = (datetime.now() - datetime.fromisoformat(d["ts"])).total_seconds()
        d["age_s"] = round(age)
        return d
    except Exception:
        return None


def worker_state(s: Settings) -> dict | None:
    """État du worker vu par l'App ; None s'il ne tourne pas (pas de battement récent)."""
    d = worker_signal(s)
    return d if d and abs(d["age_s"]) <= HEARTBEAT_MAX_AGE_S else None


def worker_absent_text(s: Settings) -> str:
    """Pourquoi le worker est vu comme arrêté (pour l'App)."""
    d = worker_signal(s)
    if not d:
        return f"non démarré (aucun signal dans {heartbeat_path(s).parent})"
    if d.get("state") == "ARRET":
        return f"arrêté sur {d.get('host')}"
    return f"dernier signal il y a {d['age_s']} s ({d.get('host')}, {d.get('ts')})"


def enqueue(s: Settings, rec: dict) -> Path:
    q = queue_dir(s)
    q.mkdir(parents=True, exist_ok=True)
    p = q / f"{rec['run_id']}.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, default=str), encoding="utf-8")
    return p


# ----------------------------------------------------------------------------- noyau par interpréteur
def kernel_for(python: str) -> str:
    """Kernelspec Jupyter pointant vers un interpréteur donné (tlone-tf4 / tlone-tf5)."""
    import hashlib
    from jupyter_core.paths import jupyter_data_dir
    name = "tlone-" + hashlib.sha1(python.encode()).hexdigest()[:8]
    d = Path(jupyter_data_dir()) / "kernels" / name
    if not (d / "kernel.json").exists():
        d.mkdir(parents=True, exist_ok=True)
        (d / "kernel.json").write_text(json.dumps({
            "argv": [python, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": f"TL-One ({python})", "language": "python"}), encoding="utf-8")
    return name


def _cell_text(cell) -> str:
    out = []
    for o in cell.get("outputs", []):
        if o.get("output_type") == "stream":
            out.append(o.get("text", ""))
        elif o.get("output_type") == "error":
            out.append(f"{o.get('ename')}: {o.get('evalue')}")
        elif o.get("output_type") in ("execute_result", "display_data"):
            out.append(str((o.get("data") or {}).get("text/plain", "")))
    return "".join(out)


class WarmNotebook:
    """Un notebook GPU dans un noyau qui reste ouvert : modèle chargé une seule fois."""

    def __init__(self, s: Settings, step: str, python: str | None = None, timeout: int = 6 * 3600):
        import nbformat
        from nbclient import NotebookClient
        self.s, self.step = s, step
        self.python = python or s.step_runtime(step)["python"]
        model = s.model_dom if step == "dom_extract" else s.model_ov
        self.nb, self.patches = nbrunner.prepare_notebook(s.notebooks[step], step, str(s.paths.data_root),
                                                          None, model or None)
        self.raw = nbformat.read(str(s.notebooks[step]), as_version=4)  # source d'origine (pour re-patcher N)
        code = [i for i, c in enumerate(self.nb.cells) if c.cell_type == "code"]
        self.cfg = next(i for i in code if CONFIG_MARKER in self.nb.cells[i].source)
        self.process = [i for i in code if any(m in self.nb.cells[i].source for m in PROCESS_MARKERS[step])]
        if not self.process:
            raise RuntimeError(f"{step} : cellule de traitement introuvable dans le notebook")
        self.client = NotebookClient(self.nb, timeout=timeout, kernel_name=kernel_for(self.python),
                                     resources={"metadata": {"path": str(s.paths.data_root)}})
        self.loaded_at = None
        self.load_seconds = None

    def _run(self, idx: int, log) -> None:
        cell = self.nb.cells[idx]
        cell.outputs = []
        try:
            self.client.execute_cell(cell, idx)
        finally:
            txt = _cell_text(cell)
            if txt:
                log(txt)

    def warm(self, log) -> None:
        """Démarre le noyau et exécute tout le notebook SAUF les cellules de traitement (modèle chargé)."""
        t0 = time.time()
        self.client.km = self.client.create_kernel_manager()
        self.client.start_new_kernel()
        self.client.start_new_kernel_client()
        for i, c in enumerate(self.nb.cells):
            if c.cell_type == "code" and i not in self.process:
                self._run(i, log)
        self.loaded_at = datetime.now().isoformat(timespec="seconds")
        self.load_seconds = round(time.time() - t0, 1)
        log(f"[worker] {self.step} prêt (modèle chargé) en {self.load_seconds} s")

    def run(self, max_items: int | None, log) -> None:
        # cellule de configuration re-patchée avec la limite N de la demande, puis traitement
        src, _ = nbrunner.patch_source(self.raw.cells[self.cfg].source, self.step, str(self.s.paths.data_root),
                                       max_items, (self.s.model_dom if self.step == "dom_extract" else self.s.model_ov)
                                       or None)
        self.nb.cells[self.cfg].source = src
        self._run(self.cfg, log)
        for i in self.process:
            self._run(i, log)

    def shutdown(self) -> None:
        try:
            self.client._cleanup_kernel()
        except Exception:
            pass


# ----------------------------------------------------------------------------- boucle
class Worker:
    def __init__(self, s: Settings | None = None, steps=GPU_STEPS, prewarm: bool = False, poll_s: float = 3.0,
                 pythons: dict | None = None):
        self.s = s or load_settings()
        self.steps = tuple(steps)
        self.prewarm = prewarm
        self.poll_s = poll_s
        self.pythons = pythons or {}
        self.warm: dict[str, WarmNotebook] = {}
        self.current = None
        self.done = 0

    def beat(self, state: str = "ATTENTE") -> None:
        p = heartbeat_path(self.s)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"), "epoch": time.time(), "host": socket.gethostname(), "pid": os.getpid(),
            "state": state, "current": self.current, "done": self.done, "steps": list(self.steps) + ["dom_post"],
            "warm": {k: {"loaded_at": w.loaded_at, "load_seconds": w.load_seconds} for k, w in self.warm.items()},
            "app_dir": str(APP_DIR)}, ensure_ascii=False), encoding="utf-8")

    def _status(self, run_id: str, **kw) -> None:
        nbrunner._write_status(self.s.paths.runs_dir / f"{run_id}.status.json", run_id=run_id, **kw)

    def handle(self, req: dict) -> None:
        run_id, step = req["run_id"], req["step"]
        log_path = self.s.paths.runs_dir / f"{run_id}.log"
        self.current = run_id
        self.beat("TRAITEMENT")

        def log(txt: str) -> None:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(txt if txt.endswith("\n") else txt + "\n")
            print(txt, end="" if txt.endswith("\n") else "\n", flush=True)

        if step == "dom_post" or step not in self.steps:  # Partie 2 (CPU) : à froid, comme un job
            py = self.pythons.get(step) or self.s.step_runtime(step)["python"]
            cmd = [py, str(APP_DIR / "run_step.py"), step, "--run-id", run_id,
                   "--data-root", str(self.s.paths.data_root)] + (["--max", str(req["max_items"])]
                                                                   if req.get("max_items") else [])
            with log_path.open("a", encoding="utf-8") as fh:
                subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=str(APP_DIR))
            return
        self._status(run_id, step=step, status="RUNNING", started_at=datetime.now().isoformat(timespec="seconds"),
                     mode="worker", max_items=req.get("max_items"), log=str(log_path))
        try:
            if step not in self.warm:
                log(f"[worker] chargement de {step} (une seule fois)…")
                w = WarmNotebook(self.s, step, self.pythons.get(step))
                self.warm[step] = w
                w.warm(log)
                self.beat("TRAITEMENT")
            w = self.warm[step]
            t0 = time.time()
            w.run(req.get("max_items"), log)
            self._status(run_id, status="SUCCEEDED", patches=w.patches, duree_traitement_s=round(time.time() - t0, 1),
                         modele_charge_le=w.loaded_at)
        except Exception as exc:  # noqa: BLE001
            log(traceback.format_exc())
            self._status(run_id, status="FAILED", error=repr(exc)[:4000])
            # noyau dans un état incertain : il sera rechargé à la prochaine demande
            if step in self.warm:
                self.warm.pop(step).shutdown()
        finally:
            self._status(run_id, finished_at=datetime.now().isoformat(timespec="seconds"))
            self.current = None
            self.done += 1

    def next_request(self) -> tuple[Path, dict] | None:
        q = queue_dir(self.s)
        for p in sorted(q.glob("*.json")) if q.exists() else []:
            taken = p.with_suffix(".taken")
            try:
                p.rename(taken)  # prise atomique : une demande n'est traitée qu'une fois
            except OSError:
                continue
            try:
                return taken, json.loads(taken.read_text(encoding="utf-8"))
            except Exception:
                continue
        return None

    def loop(self, once: bool = False) -> None:
        print(f"[worker] TL-One — données {self.s.paths.data_root} — étapes {self.steps} — Ctrl+C pour arrêter",
              flush=True)
        if self.prewarm:
            for st in self.steps:
                w = WarmNotebook(self.s, st, self.pythons.get(st))
                self.warm[st] = w
                self.beat(f"CHARGEMENT {st}")
                w.warm(lambda t: print(t, end="" if t.endswith("\n") else "\n", flush=True))
        try:
            while True:
                self.beat()
                got = self.next_request()
                if got:
                    path, req = got
                    print(f"[worker] demande {req.get('run_id')} ({req.get('step')}, N={req.get('max_items')})",
                          flush=True)
                    self.handle(req)
                    path.rename(path.with_suffix(".done"))
                    if once:
                        return
                elif once:
                    return
                else:
                    time.sleep(self.poll_s)
        except KeyboardInterrupt:
            print("\n[worker] arrêt demandé", flush=True)
            once = False
        finally:
            if not once:  # arrêt réel : on libère le GPU et on signale l'arrêt à l'App
                self.stop()

    def stop(self) -> None:
        for w in self.warm.values():
            w.shutdown()
        self.warm.clear()
        try:
            heartbeat_path(self.s).unlink()
        except OSError:
            pass


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Worker GPU TL-One (modèles chargés une fois)")
    ap.add_argument("--steps", default="dom_extract,ov_extract",
                    help="étapes GPU gardées en mémoire (dom_extract,ov_extract ; une seule si la mémoire GPU manque)")
    ap.add_argument("--prewarm", action="store_true", help="charger les modèles dès le démarrage")
    ap.add_argument("--data-root", default=None)
    a = ap.parse_args(argv)
    if a.data_root:
        os.environ["TLONE_DATA_ROOT"] = a.data_root
    steps = [x.strip() for x in a.steps.split(",") if x.strip() in GPU_STEPS]
    Worker(load_settings(), steps, prewarm=a.prewarm).loop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
