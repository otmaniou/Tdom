"""Composants Streamlit partagés."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from . import jobs, preflight
from .common import audit, current_user, find_pdf, page_count, render_page
from .config import APP_VERSION, STEPS, load_settings

_V = tuple(int(x) for x in st.__version__.split(".")[:2])
# Compatibilité : `width="stretch"` (>= 1.48) remplace `use_container_width` (déprécié).
W = {"width": "stretch"} if _V >= (1, 48) else {"use_container_width": True}

STATUS_ICON = {"SUCCEEDED": "✅", "FAILED": "❌", "RUNNING": "⏳", "EN_FILE": "🕓", "ABANDONNE": "⛔"}


def setup(title: str):
    st.set_page_config(page_title=f"TL-One · {title}", page_icon="🏦", layout="wide")
    s = load_settings()
    s.paths.ensure()
    with st.sidebar:
        st.caption(f"{APP_VERSION} · mode **{s.run_mode}**")
        st.caption(f"Données : `{s.paths.data_root}`")
        st.caption(f"Utilisateur : **{current_user()}**")
        gen = preflight.blocking(preflight.check_general(s))
        if gen:
            st.error(f"{len(gen)} prérequis bloquant(s) — voir l'Accueil")
    return s


def fmt_dzd(v) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y %H:%M") if p.exists() else "—"


def upload_pdfs(folder: Path, key: str):
    files = st.file_uploader("Déposer des PDF", type=["pdf", "PDF"], accept_multiple_files=True, key=key)
    if files and st.button(f"Copier {len(files)} fichier(s) dans `{folder.name}`", key=key + "_btn"):
        folder.mkdir(parents=True, exist_ok=True)
        for f in files:
            (folder / f.name).write_bytes(f.getbuffer())
        audit(load_settings().paths.audit_log, "UPLOAD_PDF", current_user(), dossier=str(folder),
              fichiers=[f.name for f in files])
        st.success(f"{len(files)} fichier(s) copiés.")
    n = sum(1 for q in folder.glob("*") if q.suffix.lower() == ".pdf") if folder.exists() else 0
    st.caption(f"{n} PDF présents dans `{folder}`")


def job_panel(s, step: str, help_text: str = ""):
    meta = STEPS[step]
    with st.container(border=True):
        st.markdown(f"**{meta['label']}**")
        if help_text:
            st.caption(help_text)
        c1, c2 = st.columns([1, 2])
        test = c1.number_input("Limiter à N dossiers (0 = tous)", min_value=0, value=0, step=1, key=f"max_{step}")
        rt = s.step_runtime(step)
        c2.caption(f"Exécution : {'Domino Job' if s.run_mode == 'domino' else 'processus local'}"
                   + (f" · tier `{rt['tier']}`" if rt["tier"] else "")
                   + (f" · env `{rt['environment']}`" if rt["environment"] else "")
                   + (f" · python `{rt['python']}`" if rt["python"] else "")
                   + f" · notebook `{s.notebooks[step].name}`"
                   + f" · modèle `{rt['model'] or 'MODEL_PATH du notebook'}`" if meta["gpu"] else
                   f"Exécution : {'Domino Job' if s.run_mode == 'domino' else 'processus local'}"
                   + (f" · tier `{rt['tier']}`" if rt["tier"] else "") + f" · notebook `{s.notebooks[step].name}` · sans modèle")
        # ---- Contrôle des prérequis : aucun lancement tant qu'un point est BLOQUANT ----
        rows = preflight.check_step(s, step)
        ko = preflight.blocking(rows)
        with st.expander(f"Prérequis du lancement — {'✅ tout est prêt' if not ko else f'❌ {len(ko)} point(s) bloquant(s)'}",
                         expanded=bool(ko)):
            st.dataframe(pd.DataFrame(rows), hide_index=True, **W)
        if ko:
            st.error("Lancement désactivé : " + " · ".join(f"{r['contrôle']} ({r['action'] or r['valeur']})" for r in ko))
        confirm = True
        if meta["gpu"] and not ko:
            confirm = c2.checkbox(f"Je confirme le lancement d'un job GPU sur "
                                  f"{int(test) if test else 'tous les'} dossier(s)", key=f"ok_{step}")
        if c2.button("▶ Lancer", key=f"run_{step}", type="primary", disabled=bool(ko) or not confirm):
            try:
                rec = jobs.launch(s, step, int(test) or None, current_user())
                audit(s.paths.audit_log, "JOB_LAUNCH", current_user(), **{k: v for k, v in rec.items() if k != "user"})
                st.success(f"Lancé : {rec['run_id']}" + (f" (job Domino {rec.get('domino_job_id')})"
                                                          if rec.get("domino_job_id") else ""))
                st.session_state.pop(f"ok_{step}", None)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Lancement impossible : {exc}")
        pend = preflight.pending_runs(s, step)
        if pend:
            pick = st.selectbox("Run resté en attente (job arrêté dans Domino) :", [r["run_id"] for r in pend],
                                key=f"ab_{step}")
            if st.button("Marquer abandonné", key=f"abb_{step}"):
                jobs.mark_abandoned(s, pick, current_user())
                audit(s.paths.audit_log, "JOB_ABANDON", current_user(), run_id=pick)
                st.rerun()
        runs = [r for r in jobs.list_runs(s, 200) if r.get("step") == step][:5]
        if runs:
            df = pd.DataFrame([{
                "": STATUS_ICON.get(r.get("status"), "•"), "run": r["run_id"], "statut": r.get("status"),
                "lancé": r.get("launched_at"), "fin": r.get("finished_at"), "par": r.get("user"),
                "N": r.get("max_items"), "patchs": ", ".join(r.get("patches") or []),
                "erreur": (r.get("error") or "")[:160]} for r in runs])
            st.dataframe(df, hide_index=True, **W)
            last = runs[0]
            if last.get("log") and Path(last["log"]).exists():
                with st.expander("Journal du dernier run local"):
                    st.code(Path(last["log"]).read_text(encoding="utf-8", errors="replace")[-6000:])
            if last.get("executed_notebook") and Path(last["executed_notebook"]).exists():
                st.download_button("Notebook exécuté (audit)", Path(last["executed_notebook"]).read_bytes(),
                                   file_name=Path(last["executed_notebook"]).name, key=f"dl_{step}")
        if st.button("↻ Rafraîchir", key=f"refresh_{step}"):
            st.rerun()


def pdf_viewer(folder: Path, fichier: str | None, page: int | None, key: str):
    pdf = find_pdf(folder, fichier)
    if pdf is None:
        st.info(f"PDF « {fichier} » introuvable dans `{folder}`.")
        return
    n = page_count(pdf)
    default = int(page) if page and str(page).isdigit() else 1
    pg = st.number_input(f"Page (1–{n})", min_value=1, max_value=max(n, 1), value=min(max(default, 1), max(n, 1)),
                         key=key)
    png = render_page(pdf, pg)
    if png:
        st.image(png, **W)
