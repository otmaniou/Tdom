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
.block-container {padding-top: 3.4rem; max-width: 1400px;}
[data-testid="stSidebarNav"] {display: none;}
[data-testid="stSidebar"] {background: #F3F7F5; border-right: 1px solid #E1EAE5;}
[data-testid="stSidebar"] [data-testid="stPageLink"] a {border-radius: 8px; padding: 2px 6px;}
[data-testid="stMetricValue"] {color: #0B3D2E;}
.tl-brand {display:flex; align-items:center; gap:10px; margin: 2px 0 10px 0;}
.tl-brand .logo {width:38px; height:38px; border-radius:10px; background: linear-gradient(135deg,#0B3D2E,#00915A);
                 color:#fff; font-weight:800; display:flex; align-items:center; justify-content:center; font-size:1rem;}
.tl-brand .nm {font-weight:800; font-size:1.2rem; color:#0B3D2E; line-height:1.1;}
.tl-brand .sb {color:#5B6B64; font-size:.78rem;}
.tl-navtitle {font-size:.72rem; letter-spacing:.06em; text-transform:uppercase; color:#7A8A83; margin:10px 0 2px 4px;}
.tl-hero {background: linear-gradient(120deg, #0B3D2E 0%, #00915A 100%); color: #fff; border-radius: 14px;
          padding: 18px 24px; margin-bottom: 12px;}
.tl-hero h1 {color: #fff; font-size: 1.7rem; margin: 0 0 4px 0; padding: 0;}
.tl-hero p {color: #E3F2EC; margin: 0; font-size: 0.98rem;}
.tl-hero .et {display:inline-block; background: rgba(255,255,255,.18); border-radius: 999px; padding: 1px 10px;
              font-size: .78rem; margin-bottom: 6px; color:#fff;}
.tl-chip {display:inline-block; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.35);
          border-radius: 999px; padding: 2px 10px; margin: 8px 6px 0 0; font-size: .82rem; color:#fff;}
.tl-guide {display:flex; gap:10px; flex-wrap:wrap; margin: 4px 0 12px 0;}
.tl-guide .g {flex:1 1 180px; border:1px solid #DCE7E2; background:#fff; border-radius:12px; padding:10px 12px;}
.tl-guide .g b {color:#0B3D2E;} .tl-guide .g span {display:block; color:#5B6B64; font-size:.82rem; margin-top:2px;}
.tl-guide .g .n {display:inline-block; width:22px; height:22px; border-radius:50%; background:#00915A; color:#fff;
                 text-align:center; line-height:22px; font-size:.78rem; font-weight:700; margin-right:6px;}
.tl-step {border: 1px solid #DCE7E2; border-radius: 12px; padding: 12px 14px; background: #fff; height: 100%;}
.tl-step .n {display:inline-block; width: 26px; height: 26px; border-radius: 50%; background: #00915A; color: #fff;
             text-align:center; line-height: 26px; font-weight: 700; margin-right: 8px; font-size: .85rem;}
.tl-step .t {font-weight: 700; color: #0B3D2E;}
.tl-step .a {font-size: .78rem; color: #5B6B64; margin-top: 2px;}
.tl-step .k {font-size: 1.35rem; font-weight: 700; color: #00915A; margin-top: 6px;}
.tl-step .s {font-size: .80rem; color: #39463F;}
.tl-step.ext {background: #F7F7F4; border-style: dashed;}
.tl-step.ext .n {background: #8A958F;}
.tl-todo {border:1px solid #DCE7E2; border-radius:14px; padding:14px 16px; background:#fff; min-height:218px;}
.tl-todo .ic {font-size:1.6rem;} .tl-todo .t {font-weight:700; color:#0B3D2E; font-size:1.02rem; margin-top:4px;}
.tl-todo .k {font-size:2rem; font-weight:800; color:#00915A; line-height:1.1; margin-top:6px;}
.tl-todo .k.warn {color:#B26B00;} .tl-todo .k.zero {color:#9AA8A1;}
.tl-todo .s {font-size:.84rem; color:#4C5A53; margin-top:2px;}
.tl-ok {color: #00915A; font-weight: 600;} .tl-ko {color: #B3261E; font-weight: 600;} .tl-wa {color: #B26B00; font-weight: 600;}
.tl-box {border-radius: 12px; padding: 14px 16px; border: 1px solid #DCE7E2; background: #fff;}
.tl-old {background: #FBF4F2; border-color: #F0D5CF;} .tl-new {background: #EEF8F3; border-color: #CBE8DA;}
.tl-engine {border-radius:10px; padding:8px 10px; font-size:.86rem; margin:6px 0;}
.tl-engine.ok {background:#E7F5EE; color:#0B5A3A;} .tl-engine.wa {background:#FFF4E0; color:#7A4A00;}
.tl-engine.ko {background:#FCEBEA; color:#8A1F17;}
</style>
"""

# Parcours de bout en bout (barre latérale) : libellés métier, indépendants des noms de fichiers.
NAV = [("Accueil.py", "Tableau de bord", "🏠"),
       ("pages/1_Controles_DOM.py", "1 · Domiciliations (DOM)", "📄"),
       ("pages/2_Planning_TL.py", "2 · Échéancier des transferts", "📅"),
       ("pages/3_Transferts_OV.py", "3 · Ordres de virement (OV)", "💸"),
       ("pages/4_Historique_TL.py", "4 · Exécution & suivi", "🔎"),
       ("pages/5_Fichiers_BOCI.py", "5 · Fichiers BOCI", "📤"),
       ("pages/0_Employeurs.py", "Employeurs", "🏢")]


def expert() -> bool:
    """Vue experte (administration, colonnes techniques, paramètres) ; par défaut : vue essentielle."""
    return bool(st.session_state.get("_expert", False))


def _expert_changed(key: str) -> None:
    st.session_state["_expert"] = bool(st.session_state.get(key))


def guide(etapes: list[tuple[str, str]]) -> None:
    """Bandeau « comment faire » en 2-4 étapes numérotées (vue essentielle)."""
    if expert():
        return
    h = "".join(f"<div class='g'><span class='n'>{i}</span><b>{t}</b><span>{d}</span></div>"
                for i, (t, d) in enumerate(etapes, 1))
    st.markdown(f"<div class='tl-guide'>{h}</div>", unsafe_allow_html=True)


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
        st.markdown("<div class='tl-brand'><div class='logo'>TL</div><div><div class='nm'>TL-One</div>"
                    "<div class='sb'>Transfert libre des salaires<br>BNP Paribas El Djazaïr</div></div></div>",
                    unsafe_allow_html=True)
        emp = _employer_picker(title)
        st.markdown("<div class='tl-navtitle'>Parcours</div>", unsafe_allow_html=True)
        for page, lab, icon in NAV:
            try:
                st.page_link(page, label=lab, icon=icon)
            except Exception:  # noqa: BLE001  page absente (AppTest d'une page isolée)
                pass
    s = load_settings(emp)
    s.paths.ensure()
    with st.sidebar:
        if s.run_mode == "worker":
            from .config import APP_DIR
            from .worker import commande_worker, worker_absent_text, worker_state
            w = worker_state(s)
            etat = str((w or {}).get("state") or "")
            if w and w.get("app_dir") and str(w["app_dir"]) != str(APP_DIR):
                st.markdown("<div class='tl-engine wa'>🟠 Moteur IA : version à mettre à jour</div>", unsafe_allow_html=True)
                if expert():
                    st.caption(f"Lancé depuis {w['app_dir']} (l'App tourne depuis {APP_DIR}) : le relancer depuis ce dossier.")
            elif w and etat.startswith("CHARGEMENT"):
                st.markdown("<div class='tl-engine wa'>🟠 Moteur IA en préparation (quelques minutes)</div>",
                            unsafe_allow_html=True)
            elif w:
                occ = " — lecture en cours" if w.get("current") else ""
                st.markdown(f"<div class='tl-engine ok'>🟢 Moteur IA prêt{occ}</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='tl-engine ko'>🔴 Moteur IA arrêté</div>", unsafe_allow_html=True)
                if expert():
                    st.caption(f"Worker GPU : {worker_absent_text(s)}.")
                    with st.expander("Commande de lancement du worker"):
                        st.code(commande_worker(s), language="bash")
                else:
                    st.caption("La lecture de nouveaux documents est indisponible ; tout le reste fonctionne.")
        gen = preflight.blocking(preflight.check_general(s))
        if gen and expert():
            st.error(f"{len(gen)} prérequis bloquant(s) — voir l'Accueil")
        k = f"_exp_{title}"
        st.toggle("Vue experte", value=expert(), key=k, on_change=_expert_changed, args=(k,),
                  help="Affiche les paramètres, les colonnes techniques et l'administration. "
                       "Par défaut : l'essentiel pour traiter les dossiers.")
        if expert():
            st.caption(f"{APP_VERSION} · mode **{s.run_mode}** · {current_user()}")
            with st.expander("Données", expanded=False):
                st.caption(f"`{s.paths.data_root}`")
        else:
            st.caption(f"Connecté : {current_user()}")
    st.session_state["_settings_emp"] = s.employeur
    return s


def current_settings():
    """Paramètres de l'employeur choisi dans cette session (pour les composants qui n'ont pas `s`)."""
    return load_settings(st.session_state.get("employeur"))


def hero(title: str, subtitle: str, chips: list[str] | None = None, etape: str | None = None,
         expert_subtitle: str | None = None) -> None:
    """En-tête de page : titre métier, une phrase claire ; détails techniques (chips, sous-titre) en vue experte."""
    sub = expert_subtitle if (expert() and expert_subtitle) else subtitle
    chips_html = "".join(f"<span class='tl-chip'>{c}</span>" for c in (chips or [])) if expert() else ""
    et = f"<span class='et'>{etape}</span><br>" if etape else ""
    st.markdown(f"<div class='tl-hero'>{et}<h1>{title}</h1><p>{sub}</p>{chips_html}</div>", unsafe_allow_html=True)


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
            suivi(s, pend[0]["run_id"])
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


# =============================================================================== vue essentielle / experte
def onglets(spec: list[tuple[str, bool]]):
    """Onglets d'une page. spec = [(libellé, expert_seulement)]. Un onglet réservé à la vue experte est absent de la
    vue essentielle : il est rendu None (la page saute son contenu avec `if t:`)."""
    vis = [lab for lab, exp in spec if expert() or not exp]
    tabs = dict(zip(vis, st.tabs(vis)))
    return [tabs.get(lab) for lab, _ in spec]


# Contrôles en langage courant (vue essentielle) ; le code reste visible en vue experte.
CONTROLE_SIMPLE = {
    "T01": "Toutes les pièces du dossier sont présentes", "T02": "Mentions obligatoires de l'OV lues",
    "T03": "Montant en chiffres = montant en lettres", "T04": "Le mois demandé est prévu au planning",
    "T05": "Compte débité = compte du salarié", "T06": "Même salarié sur toutes les pièces",
    "T07": "Même période sur toutes les pièces", "T14": "Mois pas déjà transféré",
    "T15": "Total transféré ≤ montant domicilié", "T17": "Devise de l'OV",
    "R01": "Salarié présent dans la base RH du mois", "R02": "Montant = part prévue par l'employeur",
    "R08": "Nombre de jours = base RH",
}
SEVERITE_SIMPLE = {"BLOQUANT": "Bloquant", "REVIEW": "À vérifier", "INFO": "Information"}


def controles_lisibles(df):
    """Tableau des contrôles d'un dossier : libellés courants, sans code ni référentiel interne (vue essentielle)."""
    if df is None or df.empty or expert():
        return df
    d = df.copy()
    if "CODE" in d.columns and "CONTROLE" in d.columns:
        d["CONTROLE"] = [CONTROLE_SIMPLE.get(c, lib) for c, lib in zip(d["CODE"], d["CONTROLE"])]
    if "SEVERITE" in d.columns:
        d["SEVERITE"] = d["SEVERITE"].map(lambda v: SEVERITE_SIMPLE.get(v, v))
    return d


# =============================================================================== lecture par l'IA (barre de progression)
LIB_ETAPE = {"dom_extract": "Lecture des domiciliations par l'IA", "dom_post": "Contrôles automatiques des domiciliations",
             "ov_extract": "Lecture des ordres de virement par l'IA"}


def _run(s, run_id: str) -> dict | None:
    return next((r for r in jobs.list_runs(s, 200) if r["run_id"] == run_id), None)


@st.fragment(run_every=3)
def suivi(s, run_id: str):
    """Avancement d'un traitement, mis à jour toutes les 3 s ; la page se recharge quand il se termine."""
    from . import avancement as av
    from .worker import worker_state
    r = _run(s, run_id)
    if r is None:
        return
    statut = r.get("status")
    if statut not in ("EN_FILE", "RUNNING"):
        st.rerun()                                        # terminé : la page entière se met à jour
    step = r.get("step")
    w = worker_state(s) if s.run_mode == "worker" else None
    with st.container(border=True):
        st.markdown(f"**{LIB_ETAPE.get(step, step)}**")
        if w and str(w.get("state", "")).startswith("CHARGEMENT"):
            st.progress(0.0, text="🧠 Le moteur IA se prépare (chargement du modèle, quelques minutes)…")
        elif statut == "EN_FILE" and not (w and w.get("current") == run_id):
            st.progress(0.0, text="🕓 Demande transmise au moteur IA : démarrage dans quelques secondes "
                                  "(ou à la fin du traitement en cours)…")
        elif step in av.ETAPES_LECTURE:
            e = av.etat(s, r)
            frac = e["lus"] / e["total"] if e["total"] else 0.0
            txt = f"🤖 L'IA lit vos documents… **{e['lus']} / {e['total']}**"
            if e["en_cours"]:
                txt += f" · en cours : {e['en_cours']}"
            if e["eta_s"]:
                txt += f" · reste {av.duree(e['eta_s'])}"
            st.progress(min(max(frac, 0.02), 1.0), text=txt)
        else:
            try:
                ec = int(max(datetime.now().timestamp() - datetime.fromisoformat(r["launched_at"]).timestamp(), 0))
            except (KeyError, ValueError, TypeError):
                ec = 0
            st.progress(0.5, text=f"🔎 Contrôles automatiques en cours (identité, dates, montants, Carthago)… {ec // 60} min {ec % 60:02d} s")
        if r.get("ensuite"):
            st.caption("Les contrôles automatiques démarreront d'eux-mêmes à la fin de la lecture.")
        if expert():
            st.caption(f"run {run_id} · {statut}")


def _dernier(s, steps: tuple) -> dict | None:
    rs = [r for r in jobs.list_runs(s, 200) if r.get("step") in steps]
    return rs[0] if rs else None


def lecture_panel(s, step: str, titre: str, explication: str, dossier: Path, upload_key: str,
                  ensuite: str | None = None) -> None:
    """Vue essentielle : déposer des documents (un seul ou des centaines) puis un bouton « Faire lire par l'IA ».
    Les documents déjà lus ne sont jamais relus. Avancement en direct ; à la fin, lien vers la vérification."""
    from . import avancement as av
    with st.container(border=True):
        st.markdown(f"#### {titre}")
        st.caption(explication)
        files = st.file_uploader("Glissez ici les PDF (un dossier ou des centaines à la fois)", type=["pdf", "PDF"],
                                 accept_multiple_files=True, key=upload_key)
        if files and st.button(f"➕ Ajouter {len(files)} document(s)", key=upload_key + "_btn"):
            dossier.mkdir(parents=True, exist_ok=True)
            for f in files:
                (dossier / Path(f.name).name).write_bytes(f.getbuffer())
            audit(s.paths.audit_log, "UPLOAD_PDF", current_user(), dossier=str(dossier), fichiers=[f.name for f in files])
            st.session_state[upload_key + "_ok"] = len(files)
            st.rerun()
        if st.session_state.pop(upload_key + "_ok", None):
            st.success("Documents ajoutés.")
        steps = (step, ensuite) if ensuite else (step,)
        pend = [r for st_ in steps for r in preflight.pending_runs(s, st_)]
        nouveaux = av.a_lire(s, step)
        total = len(av._pdfs(dossier))
        c = st.columns(3)
        c[0].metric("Documents déposés", total)
        c[1].metric("Déjà lus par l'IA", total - len(nouveaux))
        c[2].metric("À lire", len(nouveaux))
        if pend:
            suivi(s, pend[0]["run_id"])
            return
        ko = preflight.blocking(preflight.check_step(s, step))
        if ko and nouveaux:
            if any(r.get("contrôle") == "Worker GPU" for r in ko):
                st.warning("🔴 Le moteur IA n'est pas démarré : la lecture de nouveaux documents attend son lancement "
                           "(équipe Data). La vérification des dossiers déjà lus reste possible.")
            else:
                st.warning("La lecture par l'IA n'est pas disponible pour le moment : configuration du moteur à vérifier "
                           "par l'équipe Data (détail en vue experte). La vérification des dossiers déjà lus reste possible.")
            if expert():
                st.caption(" · ".join(f"{r['contrôle']} : {r.get('action') or r.get('valeur')}" for r in ko))
        lab = (f"▶ Faire lire {len(nouveaux)} document(s) par l'IA" if nouveaux else "Aucun nouveau document à lire")
        if st.button(lab, type="primary", disabled=bool(ko) or not nouveaux, key=f"lire_{step}", **W):
            try:
                rec = jobs.launch(s, step, None, current_user(), ensuite=ensuite if s.run_mode == "worker" else None)
                audit(s.paths.audit_log, "JOB_LAUNCH", current_user(), **{k: v for k, v in rec.items() if k != "user"})
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Lecture impossible : {exc}")
        last = _dernier(s, steps)
        if last and last.get("status") == "FAILED":
            st.error(f"Le dernier traitement ({LIB_ETAPE.get(last.get('step'), last.get('step'))}) s'est arrêté sur une "
                     "erreur. Détail : vue experte.")
        elif last and last.get("status") == "SUCCEEDED":
            try:
                dfin = datetime.fromisoformat(str(last.get("finished_at")))
                fin, recent = dfin.strftime("%d/%m/%Y à %H:%M"), (datetime.now() - dfin).total_seconds() < 3600
            except (ValueError, TypeError):
                fin, recent = "—", False
            if recent:
                st.success(f"✅ Traitement terminé le {fin} : les dossiers sont prêts dans l'onglet ② Vérifier et valider.")
            else:
                st.caption(f"✅ Dernier traitement terminé le {fin}.")
        if ensuite and s.run_mode != "worker":
            st.caption("Après la lecture, lancez les contrôles automatiques (vue experte).")


def a_faire(cartes: list[dict]) -> None:
    """Cartes « à faire » : icône, titre, nombre, phrase, lien. Une carte à 0 est grisée."""
    cols = st.columns(len(cartes))
    for col, c in zip(cols, cartes):
        with col:
            k = c.get("k", 0)
            cls = "zero" if not k else ("warn" if c.get("warn") else "")
            st.markdown(f"<div class='tl-todo'><div class='ic'>{c['ic']}</div><div class='t'>{c['t']}</div>"
                        f"<div class='k {cls}'>{c.get('kk', k)}</div><div class='s'>{c['s']}</div></div>",
                        unsafe_allow_html=True)
            if c.get("page"):
                st.page_link(c["page"], label=c.get("lien", "Ouvrir"), icon="➡️")


# En-têtes de colonnes en clair (vue essentielle)
COL_FR = {"PERIODE_TL": "Période", "NOM_TRAVAILLEUR": "Salarié", "SIEGE_RACINE": "Identifiant client",
          "NUMERO_DOMICILIATION": "N° domiciliation", "TYPE_VERSION": "Contrat", "DATE_DEBUT_SEGMENT": "Du",
          "DATE_FIN_SEGMENT": "Au", "MONTANT_MAX_THEORIQUE": "Montant autorisé (DZD)",
          "MONTANT_TRANSFERE": "Déjà transféré (DZD)", "RELIQUAT": "Reste à régulariser (DZD)",
          "SOLDE_RESTANT": "Solde de la période (DZD)", "STATUT_PERIODE": "Situation",
          "PART_TRANSFERABLE_CTS": "Part mensuelle (DZD)", "NUMERO_AUGMENTATION": "N° augmentation",
          "PERIODES": "Mois", "DEBUT": "Début", "FIN": "Fin", "AUGMENTATIONS": "Augmentations",
          "MONTANT_DOMICILIE": "Montant domicilié (DZD)", "TRANSFERE": "Transféré (DZD)", "SOLDE_DOM": "Reste (DZD)",
          "FICHIER_SOURCE": "Dossier"}
VERSION_FR = {"NOUVEAU_CONTRAT": "Contrat initial", "AUGMENTATION": "Augmentation"}
