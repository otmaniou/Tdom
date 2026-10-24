"""Composants Streamlit partagés."""
from __future__ import annotations

import os
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

MODE_LABEL = {"domino": "Domino Job", "local": "processus local", "worker": "worker GPU (modèle déjà chargé)"}
STATUS_ICON = {"SUCCEEDED": "✅", "FAILED": "❌", "RUNNING": "⏳", "EN_FILE": "🕓", "ABANDONNE": "⛔"}


GREEN, DARK = "#00915A", "#0B3D2E"
CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1400px;}
[data-testid="stSidebar"] {background: #F4F8F6;}
.tl-hero {background: linear-gradient(120deg, #0B3D2E 0%, #00915A 100%); color: #fff; border-radius: 14px;
          padding: 22px 26px; margin-bottom: 14px;}
.tl-hero h1 {color: #fff; font-size: 1.9rem; margin: 0 0 4px 0;}
.tl-hero p {color: #E3F2EC; margin: 0; font-size: 0.98rem;}
.tl-chip {display:inline-block; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.35);
          border-radius: 999px; padding: 2px 10px; margin: 8px 6px 0 0; font-size: .82rem; color:#fff;}
.tl-step {border: 1px solid #DCE7E2; border-radius: 12px; padding: 12px 14px; background: #fff; height: 100%;}
.tl-step .n {display:inline-block; width: 26px; height: 26px; border-radius: 50%; background: #00915A; color: #fff;
             text-align:center; line-height: 26px; font-weight: 700; margin-right: 8px; font-size: .85rem;}
.tl-step .t {font-weight: 700; color: #0B3D2E;}
.tl-step .a {font-size: .78rem; color: #5B6B64; margin-top: 2px;}
.tl-step .k {font-size: 1.35rem; font-weight: 700; color: #00915A; margin-top: 6px;}
.tl-step .s {font-size: .80rem; color: #39463F;}
.tl-step.ext {background: #F7F7F4; border-style: dashed;}
.tl-step.ext .n {background: #8A958F;}
.tl-ok {color: #00915A; font-weight: 600;} .tl-ko {color: #B3261E; font-weight: 600;} .tl-wa {color: #B26B00; font-weight: 600;}
.tl-box {border-radius: 12px; padding: 14px 16px; border: 1px solid #DCE7E2; background: #fff;}
.tl-old {background: #FBF4F2; border-color: #F0D5CF;} .tl-new {background: #EEF8F3; border-color: #CBE8DA;}
</style>
"""


def _employer_picker(page: str = ""):
    """Choix de l'employeur courant (gardé pour toute la session, toutes les pages)."""
    from . import employeurs
    from .config import home_and_default
    home, defaut = home_and_default()
    try:
        employeurs.ensure_registered(home, defaut, os.environ.get(
            "TLONE_EMPLOYEUR_RAISON_SOCIALE", "TOSYALI IRON STEEL INDUSTRY ALGERIE" if defaut == "TOSYALI" else ""))
    except OSError:
        pass
    reg = employeurs.load(home)
    reg = reg[reg["ACTIF"].fillna("OUI") != "NON"]
    codes = list(reg["CODE"])
    cur = st.session_state.get("employeur") or _emp_url() or defaut or (codes[0] if codes else None)
    if cur not in codes and codes:
        cur = codes[0]
    if codes:
        lab = {r.CODE: r.RAISON_SOCIALE + ("  · démo" if r.DEMO == "OUI" else "") for r in reg.itertuples()}
        nxt = st.session_state.pop("_emp_next", None)       # choix demandé par une page (bouton « Ouvrir »…)
        if nxt in codes:
            cur = nxt
        # La valeur de référence est session_state["employeur"] (jamais la clé du widget) : Streamlit recrée le
        # sélecteur à chaque changement de page et le remettrait sur le 1er employeur. La clé contient donc la page
        # et l'employeur courant ; un choix de l'utilisateur passe par le rappel _emp_changed.
        k = f"_emp_pick_{page}_{cur}"
        st.selectbox("Employeur", codes, index=codes.index(cur), format_func=lambda c: lab.get(c, c), key=k,
                     on_change=_emp_changed, args=(k,))
    st.session_state["employeur"] = cur
    _emp_url(cur)
    return cur


def _emp_url(code: str | None = None) -> str | None:
    """Employeur gardé dans l'adresse (?emp=CODE) : un rechargement de la page (F5) garde l'employeur choisi."""
    try:
        if code is None:
            v = st.query_params.get("emp")
            return v[0] if isinstance(v, list) else v
        if st.query_params.get("emp") != code:
            st.query_params["emp"] = code
    except Exception:  # noqa: BLE001  version de Streamlit sans st.query_params
        return None
    return code


def _emp_changed(key: str) -> None:
    """Rappel du sélecteur de la barre latérale (exécuté avant le script)."""
    v = st.session_state.get(key)
    if v:
        st.session_state["employeur"] = v


def choisir_employeur(code: str) -> None:
    """Change l'employeur courant depuis une page (bouton) : pris en compte au prochain affichage."""
    st.session_state["employeur"] = code
    st.session_state["_emp_next"] = code


def setup(title: str):
    st.set_page_config(page_title=f"TL-One · {title}", page_icon="🏦", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown(f"<div style='font-weight:800;font-size:1.25rem;color:{DARK}'>TL-One</div>"
                    "<div style='color:#5B6B64;font-size:.85rem;margin-bottom:8px'>Transfert libre des salaires · "
                    "BNP Paribas El Djazaïr</div>", unsafe_allow_html=True)
        emp = _employer_picker(title)
    s = load_settings(emp)
    s.paths.ensure()
    with st.sidebar:
        st.caption(f"{APP_VERSION} · mode **{s.run_mode}** · {current_user()}")
        with st.expander("Données", expanded=False):
            st.caption(f"`{s.paths.data_root}`")
        if s.run_mode == "worker":
            from .config import APP_DIR
            from .worker import commande_worker, worker_absent_text, worker_state
            w = worker_state(s)
            etat = str((w or {}).get("state") or "")
            if w and w.get("app_dir") and str(w["app_dir"]) != str(APP_DIR):
                st.warning(f"Moteur IA actif mais lancé depuis {w['app_dir']} (l'App tourne depuis {APP_DIR}) : "
                           "le relancer depuis ce dossier.")
            elif w and etat.startswith("CHARGEMENT"):
                st.warning(f"Moteur IA en cours de chargement ({etat.split(' ', 1)[-1]}) — quelques minutes.")
            elif w:
                st.success(f"Moteur IA prêt ({etat.lower()})" + (f" — {w['current']}" if w.get("current") else ""))
            else:
                st.error(f"Moteur IA (worker GPU) : {worker_absent_text(s)}.")
                with st.expander("Commande de lancement du worker"):
                    st.code(commande_worker(s), language="bash")
        gen = preflight.blocking(preflight.check_general(s))
        if gen:
            st.error(f"{len(gen)} prérequis bloquant(s) — voir l'Accueil")
    st.session_state["_settings_emp"] = s.employeur
    return s


def current_settings():
    """Paramètres de l'employeur choisi dans cette session (pour les composants qui n'ont pas `s`)."""
    return load_settings(st.session_state.get("employeur"))


def hero(title: str, subtitle: str, chips: list[str] | None = None) -> None:
    chips_html = "".join(f"<span class='tl-chip'>{c}</span>" for c in (chips or []))
    st.markdown(f"<div class='tl-hero'><h1>{title}</h1><p>{subtitle}</p>{chips_html}</div>", unsafe_allow_html=True)


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
        audit(current_settings().paths.audit_log, "UPLOAD_PDF", current_user(), dossier=str(folder),
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
        c2.caption(f"Exécution : {MODE_LABEL.get(s.run_mode, s.run_mode)}"
                   + (f" · tier `{rt['tier']}`" if rt["tier"] else "")
                   + (f" · env `{rt['environment']}`" if rt["environment"] else "")
                   + (f" · python `{rt['python']}`" if rt["python"] else "")
                   + f" · notebook `{s.notebooks[step].name}`"
                   + f" · modèle `{rt['model'] or 'MODEL_PATH du notebook'}`" if meta["gpu"] else
                   f"Exécution : {MODE_LABEL.get(s.run_mode, s.run_mode)}"
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
        for r in pend:
            ds = jobs.domino_status(r["domino_job_id"]) if r.get("domino_job_id") else None
            st.info(f"⏳ Traitement en cours : **{r['run_id']}**"
                    + (f" — statut Domino : **{ds}**" if ds else "")
                    + (f" — job {r['domino_job_id']}" if r.get("domino_job_id") else "")
                    + (". Suivi détaillé : terminal du worker GPU (ou journal ci-dessous)" if s.run_mode == "worker"
                       else ". Suivi détaillé : menu Jobs du projet")
                    + " ; cliquez « Rafraîchir » pour mettre à jour.")
        if pend:
            with st.expander("Le traitement a été arrêté (worker arrêté, job stoppé) sans que l'app le voie ?"):
                pick = st.selectbox("Run à clore", [r["run_id"] for r in pend], key=f"ab_{step}")
                st.caption("À n'utiliser que si le job n'apparaît plus comme en cours dans Domino.")
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


@st.cache_data(show_spinner="Lecture de l'historique Atlas / CarthagoTrade…", max_entries=4)
def _historique(paths: tuple, _mt: tuple, tol: float):
    from . import historique as h
    d = dict(paths)
    errs, data = [], {}
    for k, fn in (("trade", h.load_trade), ("atlas", h.load_atlas), ("blocage", h.load_blocage),
                  ("soldes", h.load_soldes)):
        if k in d:
            try:
                data[k] = fn(Path(d[k]))
            except Exception as exc:  # noqa: BLE001
                errs.append(f"{h.LABEL[k]} : {exc}")
    res = h.reconcile(data.get("atlas"), data.get("trade"), data.get("blocage"), tol=tol)
    return data, res, errs


def historique_data(P, s):
    """Exports Atlas / Trade / Blocage / Soldes les plus récents (page 4), lus une fois et mis en cache.
    Retourne (fichiers, données, rapprochement, erreurs, clé) ; clé = signature des fichiers (pour d'autres caches)."""
    from . import historique as h
    files = h.latest(P.historique_dir)
    key = tuple(sorted((k, str(p)) for k, p in files.items()))
    mt = tuple(p.stat().st_mtime for _, p in sorted(files.items()))
    if not files:
        return files, {}, {"historique": pd.DataFrame(), "anomalies": pd.DataFrame()}, [], ()
    data, res, errs = _historique(key, mt, s.tolerance_montant_dzd)
    return files, data, res, errs, key + mt


HORIZONS = ("Toute la durée", "Période actuelle", "Intervalle")


def horizon_planning(df, key: str, today=None):
    """Filtre d'affichage du Planning : toute la durée des contrats validés, le mois en cours, ou un intervalle de
    mois (du … au …). Retourne (sélection, libellé). Les calculs (reliquats, consommation) restent faits sur le
    Planning complet : seul l'affichage est filtré."""
    from datetime import date as _date
    if df is None or df.empty or "MOIS_BASE" not in df.columns:
        return df, HORIZONS[0]
    today = today or _date.today()
    cur = f"{today:%Y-%m}"
    mois = sorted(m for m in df["MOIS_BASE"].dropna().astype(str).unique())
    a, b, c = st.columns([3, 2, 2])
    h = a.radio("Périodes affichées", HORIZONS, horizontal=True, key=f"{key}_h")
    if h == HORIZONS[2]:
        i0 = mois.index(cur) if cur in mois else 0
        m0 = b.selectbox("Du mois", mois, index=i0, key=f"{key}_m0")
        fins = [m for m in mois if m >= m0]
        m1 = c.selectbox("Au mois", fins, index=len(fins) - 1, key=f"{key}_m1")
        mb = df["MOIS_BASE"].astype(str)
        return df[(mb >= m0) & (mb <= m1)], f"du {m0} au {m1}"
    if h == HORIZONS[1]:
        b.caption(f"Mois en cours : **{cur}** (P1 et P2 comprises)")
        return df[df["MOIS_BASE"].astype(str) == cur], f"période {cur}"
    b.caption(f"Du **{mois[0] if mois else '—'}** au **{mois[-1] if mois else '—'}** (contrats validés, durée complète)")
    return df, "toute la durée"


def hauteur(n: int, mx: int = 420) -> int:
    """Hauteur d'un tableau ajustée au nombre de lignes (pas de lignes vides affichées)."""
    return min(mx, 38 + 35 * max(int(n), 1))
