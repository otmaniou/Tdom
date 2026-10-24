"""Worker GPU « à chaud » pour les démonstrations (et plus tard la production).

Lancé à la main dans un workspace GPU (environnement tlone) :

    /opt/conda/envs/tlone-tf4/bin/python /mnt/code/tlone_app_v4/run_worker.py --prewarm --data-root <dossier de l'employeur>

L'App (TLONE_RUN_MODE=worker) dépose une demande dans <home>/_commun/worker/queue/ ; le worker la traite et
écrit runs/<run_id>.status.json (dans le dossier de l'employeur) comme un job : l'App affiche le résultat de la même façon.

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
import threading
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
LOOP_MARKERS = {"ov_extract": ("for pdf_path in pdfs", "pdf_path in enumerate(pdfs")}
PROCESS_MARKERS = {
    "dom_extract": ("if not pdfs:",),
    "ov_extract": ("for pdf_path in pdfs", "pdf_path in enumerate(pdfs", "pd.read_excel(EXCEL_PATH"),
}
HEARTBEAT_MAX_AGE_S = 90
BEAT_EVERY_S = 15          # battement en tâche de fond : le worker reste « vivant » pendant un chargement ou un long lot
WORKER_PYTHON = "/opt/conda/envs/tlone-tf4/bin/python"


def queue_dir(s: Settings) -> Path:
    """File commune à tous les employeurs : un seul worker GPU sert toute l'app (chaque demande porte
    le dossier de données de son employeur)."""
    return s.common_dir / "worker" / "queue"


def heartbeat_path(s: Settings) -> Path:
    return s.common_dir / "worker" / "worker_heartbeat.json"


def stop_path(s: Settings) -> Path:
    """Demande d'arrêt déposée par « run_worker.py --arreter » (depuis n'importe quel terminal)."""
    return s.common_dir / "worker" / "STOP"


def legacy_heartbeat_path(s: Settings) -> Path:
    """Emplacement du signal de vie des versions précédentes (worker lancé depuis tlone_app_v1…v3)."""
    return s.paths.runs_dir / "worker_heartbeat.json"


def commande_worker(s: Settings) -> str:
    """Commande exacte à lancer dans le workspace GPU (dossier de l'App + racine des données explicites)."""
    py = WORKER_PYTHON if Path(WORKER_PYTHON).exists() or os.environ.get("DOMINO_PROJECT_ID") else "python"
    return (f"{py} {APP_DIR / 'run_worker.py'} --steps dom_extract,ov_extract --prewarm "
            f"--data-root {s.paths.data_root}")


def _read_beat(p: Path) -> dict | None:
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
    except Exception:  # noqa: BLE001  fichier en cours d'écriture ou illisible
        return None


def worker_signal(s: Settings) -> dict | None:
    """Dernier battement du worker, même ancien (None si jamais démarré ici) ; age_s en secondes.
    L'âge vient de l'horloge epoch (indépendante du fuseau horaire de l'App et du workspace)."""
    p = heartbeat_path(s)
    for _ in range(3):           # lecture concurrente d'une écriture : on réessaie
        d = _read_beat(p)
        if d is not None or not p.exists():
            return d
        time.sleep(0.2)
    return None


def worker_state(s: Settings) -> dict | None:
    """État du worker vu par l'App ; None s'il ne tourne pas (pas de battement récent)."""
    d = worker_signal(s)
    return d if d and abs(d["age_s"]) <= HEARTBEAT_MAX_AGE_S else None


def worker_absent_text(s: Settings) -> str:
    """Pourquoi le worker est vu comme arrêté (pour l'App), avec la cause probable."""
    d = worker_signal(s)
    old = _read_beat(legacy_heartbeat_path(s))
    if not d and old and abs(old["age_s"]) <= HEARTBEAT_MAX_AGE_S:
        return (f"un worker d'une version précédente tourne (lancé depuis {old.get('app_dir', '?')} sur "
                f"{old.get('host')}) : il ne lit pas la file de cette version. Ctrl+C dans son terminal puis relancer "
                f"depuis {APP_DIR}")
    if not d:
        return (f"non démarré (aucun signal dans {heartbeat_path(s).parent}). Lancé quand même ? Vérifier que le "
                f"worker affiche « signal de vie : {heartbeat_path(s)} » ; sinon le relancer avec --data-root")
    if d.get("state") == "ARRET":
        return f"arrêté sur {d.get('host')}"
    return (f"dernier signal il y a {d['age_s']} s ({d.get('host')}, {d.get('ts')}) : worker arrêté ou "
            "workspace GPU fermé")


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
        loops = LOOP_MARKERS.get(step)
        if loops and not any(m in self.nb.cells[i].source for i in self.process for m in loops):
            raise RuntimeError(f"{step} : boucle de traitement des PDF introuvable dans {s.notebooks[step].name}")
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
        log(f"[worker] {self.step} prêt (modèle chargé) en {self.load_seconds} s — notebook "
            f"{self.s.notebooks[self.step].name}, cellules de traitement {self.process}")

    def run(self, max_items: int | None, log, data_root: str | None = None) -> None:
        # cellule de configuration re-patchée (dossier de l'employeur, limite N), puis traitement
        src, _ = nbrunner.patch_source(self.raw.cells[self.cfg].source, self.step, str(data_root or self.s.paths.data_root),
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
        self.env: dict = {}
        self.errors: dict = {}
        self.state = "ATTENTE"
        self._stop = threading.Event()
        self._beater: threading.Thread | None = None

    def probe_env(self) -> dict:
        """Versions des bibliothèques vues PAR LE WORKER (là où tournent les notebooks) : l'App s'en sert
        pour ses prérequis au lieu de sonder son propre conteneur, qui peut différer."""
        from .preflight import STEP_MODULES, probe_python
        out = {}
        for st in dict.fromkeys(list(self.steps) + ["dom_post", "ov_extract", "dom_extract"]):
            py = self.pythons.get(st) or self.s.step_runtime(st)["python"]
            r = probe_python(py, STEP_MODULES[st]) if Path(py).exists() else None
            out[st] = {"python": py, "versions": r}
        self.env = out
        return out

    def beat(self, state: str | None = None) -> None:
        """Écrit le signal de vie (écriture atomique : l'App ne lit jamais un fichier à moitié écrit)."""
        from .config import APP_VERSION
        if state:
            self.state = state
        p = heartbeat_path(self.s)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"), "epoch": time.time(),
            "host": socket.gethostname(), "pid": os.getpid(), "state": self.state, "current": self.current,
            "done": self.done, "steps": list(self.steps) + ["dom_post"],
            "warm": {k: {"loaded_at": w.loaded_at, "load_seconds": w.load_seconds} for k, w in list(self.warm.items())},
            "app_dir": str(APP_DIR), "version": APP_VERSION, "data_root": str(self.s.paths.data_root),
            "env": self.env, "errors": dict(self.errors)}, ensure_ascii=False, default=str)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, p)

    def start_beating(self) -> None:
        """Battement toutes les BEAT_EVERY_S secondes en tâche de fond, même pendant le chargement des modèles
        (plusieurs minutes) ou le traitement d'un long lot : l'App ne voit plus le worker « arrêté » à tort."""
        def run():
            while not self._stop.wait(BEAT_EVERY_S):
                try:
                    self.beat()
                except Exception as exc:  # noqa: BLE001
                    print(f"[worker] signal de vie non écrit : {exc}", flush=True)
        self.beat()
        self._beater = threading.Thread(target=run, name="tlone-heartbeat", daemon=True)
        self._beater.start()

    def _status(self, run_id: str, **kw) -> None:
        nbrunner._write_status(self.s.paths.runs_dir / f"{run_id}.status.json", run_id=run_id, **kw)

    def handle(self, req: dict) -> None:
        run_id, step = req["run_id"], req["step"]
        base = self.s
        if req.get("data_root") and str(req["data_root"]) != str(base.paths.data_root):
            # multi-employeur : chaque demande porte le dossier de son employeur (mêmes notebooks / modèles)
            import dataclasses
            from .config import Paths
            self.s = dataclasses.replace(base, paths=Paths(Path(req["data_root"])), employeur=req.get("employeur"))
        try:
            self._handle(req, run_id, step)
        finally:
            self.s = base

    def _handle(self, req: dict, run_id: str, step: str) -> None:
        self.s.paths.runs_dir.mkdir(parents=True, exist_ok=True)
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
            w.run(req.get("max_items"), log, str(self.s.paths.data_root))
            if step == "ov_extract":   # un run « réussi » doit avoir produit un nouveau classeur audit_transferts
                from .transfers import latest_audit
                new = [p for p in latest_audit(self.s.paths.tr_out) if p.stat().st_mtime >= t0 - 1]
                if not new:
                    raise RuntimeError("Aucun classeur audit_transferts_*.xlsx produit par ce run : la boucle de "
                                       "traitement du notebook n'a pas été exécutée (worker à relancer ?)")
                log(f"[worker] classeur produit : {new[0].name}")
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
            self.state = "ATTENTE"

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
        from .config import APP_VERSION
        print(f"[worker] TL-One {APP_VERSION} — code {APP_DIR}\n"
              f"[worker] données {self.s.paths.data_root} — étapes {self.steps} — Ctrl+C pour arrêter\n"
              f"[worker] signal de vie : {heartbeat_path(self.s)}\n"
              f"[worker] file des demandes : {queue_dir(self.s)}\n"
              f"[worker] arrêt : Ctrl+C ici, ou depuis un autre terminal : {sys.executable} "
              f"{APP_DIR / 'run_worker.py'} --arreter --data-root {self.s.paths.data_root}", flush=True)
        try:
            stop_path(self.s).unlink()          # demande d'arrêt restée d'un lancement précédent
        except OSError:
            pass
        if not once and threading.current_thread() is threading.main_thread():
            import signal

            def _term(signum, frame):           # pkill / kill : même arrêt propre que Ctrl+C (GPU libéré)
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, _term)
        try:
            self.start_beating()
            self.probe_env()
            for st, e in self.env.items():
                v = e["versions"] or {}
                print(f"[worker] {st} : {e['python']} — transformers {v.get('transformers')}", flush=True)
            if self.prewarm:
                for st in self.steps:
                    if self._arret_demande():
                        raise KeyboardInterrupt
                    self.beat(f"CHARGEMENT {st}")
                    try:
                        w = WarmNotebook(self.s, st, self.pythons.get(st))
                        self.warm[st] = w
                        w.warm(lambda t: print(t, end="" if t.endswith("\n") else "\n", flush=True))
                    except Exception as exc:  # noqa: BLE001  une étape en échec n'arrête pas les autres
                        print(traceback.format_exc(), flush=True)
                        msg = (str(exc).splitlines() or [repr(exc)])[-1][:300]
                        print(f"[worker] ÉCHEC du chargement de {st} : {msg}\n"
                              f"[worker] {st} reste indisponible ; les autres étapes continuent.", flush=True)
                        if st in self.warm:
                            self.warm.pop(st).shutdown()
                        self.errors[st] = msg
            self.beat("ATTENTE")
            print("[worker] prêt : en attente des demandes de l'App", flush=True)
            while True:
                if self._arret_demande():
                    break
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
            self._stop.set()  # fin du battement en tâche de fond
            if not once:  # arrêt réel : on libère le GPU et on signale l'arrêt à l'App
                self.stop()
                print("[worker] arrêté : modèles déchargés, GPU libéré, signal de vie effacé", flush=True)

    def _arret_demande(self) -> bool:
        p = stop_path(self.s)
        if not p.exists():
            return False
        try:
            p.unlink()
        except OSError:
            pass
        print("\n[worker] arrêt demandé (commande --arreter)", flush=True)
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._beater is not None and self._beater is not threading.current_thread():
            self._beater.join(timeout=5)      # pas de battement réécrit après l'effacement
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
    ap.add_argument("--arreter", action="store_true",
                    help="demander l'arrêt du worker en cours (depuis un autre terminal) et attendre sa confirmation")
    ap.add_argument("--attente", type=int, default=180, help="avec --arreter : secondes d'attente maximum")
    a = ap.parse_args(argv)
    if a.data_root:
        os.environ["TLONE_DATA_ROOT"] = a.data_root
    elif not os.environ.get("TLONE_DATA_ROOT"):
        found = _auto_data_root()
        if found:
            os.environ["TLONE_DATA_ROOT"] = str(found)
            print(f"[worker] TLONE_DATA_ROOT absent : données trouvées dans {found}", flush=True)
        else:
            print("[worker] ATTENTION : TLONE_DATA_ROOT absent et aucun dossier …/employeurs/<CODE> trouvé : le "
                  "signal de vie irait dans /mnt/data, invisible pour l'App. Relancer avec --data-root "
                  "/domino/datasets/local/<projet>/document_pipeline/employeurs/<CODE>", flush=True)
    if a.arreter:
        return arreter(load_settings(), a.attente)
    steps = [x.strip() for x in a.steps.split(",") if x.strip() in GPU_STEPS]
    Worker(load_settings(), steps, prewarm=a.prewarm).loop()
    return 0


def arreter(s: Settings, attente: int = 180) -> int:
    """Dépose la demande d'arrêt et attend que le worker l'ait prise en compte (signal de vie effacé)."""
    hb = heartbeat_path(s)
    d = worker_signal(s)
    if not hb.exists():
        print(f"[arrêt] aucun worker en cours (pas de signal de vie dans {hb.parent})")
        return 0
    pid, host = (d or {}).get("pid"), (d or {}).get("host")
    stop_path(s).parent.mkdir(parents=True, exist_ok=True)
    stop_path(s).write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    print(f"[arrêt] demande déposée pour le worker {pid} sur {host} ; un traitement en cours se termine d'abord")
    t0 = time.time()
    while time.time() - t0 < attente:
        if not hb.exists():
            print(f"[arrêt] worker arrêté en {time.time() - t0:.0f} s (modèles déchargés, GPU libéré)")
            return 0
        time.sleep(1)
    print(f"[arrêt] toujours actif après {attente} s (traitement long ?). Forcer : kill {pid} (sur {host}), puis "
          "vérifier nvidia-smi")
    return 1


def _auto_data_root() -> Path | None:
    """Domino : dataset du projet …/document_pipeline/employeurs/<CODE> (TOSYALI de préférence)."""
    cands = sorted(Path("/domino/datasets/local").glob("*/document_pipeline/employeurs/*"))
    cands = [c for c in cands if c.is_dir()]
    return next((c for c in cands if c.name == "TOSYALI"), cands[0] if cands else None)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
