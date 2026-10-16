import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from tlone import domvalid, ui  # noqa: E402
from tlone.common import audit, current_user, is_blank  # noqa: E402

s = ui.setup("Contrôles DOM")
P = s.paths
st.title("1 · Contrôles des domiciliations")
st.caption("AS-01 / AS-02 / AS-03 — DOM, CTR, CTS, TTR · extraction VLM → normalisation/DQ → validation humaine")

tab_run, tab_dash, tab_val, tab_ctx, tab_param = st.tabs(
    ["① Traitement", "② Tableau de bord", "③ Validation", "④ Contrôles & anomalies", "⑤ Paramètres"])

# ------------------------------------------------------------------ ① traitement
with tab_run:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Dossiers à traiter")
        ui.upload_pdfs(P.dom_in, "up_dom")
    with c2:
        st.subheader("Référentiel CarthagoDom")
        st.caption(f"`{P.carthago_xlsx.name}` — mis à jour le {ui.mtime(P.carthago_xlsx)}")
        up = st.file_uploader("Remplacer l'export CarthagoDom", type=["xlsx"], key="up_carthago")
        if up and st.button("Enregistrer l'export Carthago"):
            from tlone.common import backup
            backup(P.carthago_xlsx)
            P.carthago_xlsx.write_bytes(up.getbuffer())
            audit(P.audit_log, "UPLOAD_CARTHAGO", current_user(), fichier=up.name)
            st.success("Export Carthago enregistré.")
    ui.job_panel(s, "dom_extract", "Partie 1 V15-A : orientation, classification, extraction 99 champs, "
                                   "recovery 2400 px → JSON RAW par dossier. Reprise sur checkpoint (RESUME).")
    ui.job_panel(s, "dom_post", "Partie 2 V15-A : normalisation, DQ, confidence, rapprochement Carthago, "
                                "Modulo 97 → classeur de validation. ⚠️ Régénère le classeur : les décisions "
                                "déjà saisies dans l'app sont à reporter (une sauvegarde est conservée).")

# ------------------------------------------------------------------ ⑤ paramètres
with tab_param:
    st.subheader("Calendrier des augmentations")
    st.caption("Utilisé par la Partie 2 et le Planning TL : le mois d'effet d'une augmentation vient "
               "exclusivement de ce fichier (jamais de la date de signature).")
    pa = pd.read_excel(P.param_aug_xlsx) if P.param_aug_xlsx.exists() else \
        pd.DataFrame({"ANNEE_AUGMENTATION": pd.Series(dtype="Int64"), "MOIS_AUGMENTATION": pd.Series(dtype="Int64")})
    pa_ed = st.data_editor(pa, num_rows="dynamic", hide_index=True, key="pa_ed", column_config={
        "ANNEE_AUGMENTATION": st.column_config.NumberColumn(min_value=2000, max_value=2100, step=1, format="%d"),
        "MOIS_AUGMENTATION": st.column_config.NumberColumn(min_value=1, max_value=12, step=1, format="%d")})
    if st.button("Enregistrer le calendrier"):
        if pa_ed["ANNEE_AUGMENTATION"].duplicated().any():
            st.error("Une année ne peut avoir qu'un mois d'augmentation.")
        else:
            from tlone.common import backup
            backup(P.param_aug_xlsx)
            pa_ed.dropna(how="all").to_excel(P.param_aug_xlsx, index=False)
            audit(P.audit_log, "PARAM_AUGMENTATION", current_user(), valeurs=pa_ed.to_dict("records"))
            st.success("Calendrier enregistré.")

if not P.validation_xlsx.exists():
    for t in (tab_dash, tab_val, tab_ctx):
        with t:
            st.info(f"Classeur `{P.validation_xlsx.name}` absent : lancez la Partie 2.")
    st.stop()


@st.cache_data(show_spinner=False)
def _load(path: str, mt: float):
    x = Path(path)
    return domvalid.load_manual(x), domvalid.load_sheet(x, domvalid.DOSSIERS_SHEET)


MT = P.validation_xlsx.stat().st_mtime
MANUAL, DOSSIERS = _load(str(P.validation_xlsx), MT)
PROG = domvalid.progress(MANUAL)

# ------------------------------------------------------------------ ② dashboard
with tab_dash:
    st.caption(f"Classeur généré le {ui.mtime(P.validation_xlsx)}")
    n = len(DOSSIERS)
    auto = n - PROG["FICHIER"].nunique() if not PROG.empty else n
    m = st.columns(5)
    m[0].metric("Dossiers", n)
    m[1].metric("Sans validation requise", auto)
    m[2].metric("Validation terminée", int((PROG["STATUT_VALIDATION"] == "TERMINE").sum()) if not PROG.empty else 0)
    m[3].metric("En cours", int((PROG["STATUT_VALIDATION"] == "EN_COURS").sum()) if not PROG.empty else 0)
    m[4].metric("Rejetés", int((PROG["STATUT_VALIDATION"] == "REJETE").sum()) if not PROG.empty else 0)
    if "BASE_CERTIFIABLE" in DOSSIERS.columns:
        cert = DOSSIERS["BASE_CERTIFIABLE"].astype(str).str.upper().eq("TRUE").sum()
        st.progress(cert / max(n, 1), text=f"Base certifiable (compte local + réf. DOM confirmés Carthago) : {cert}/{n}")
    cols = [c for c in ["FICHIER", "TYPE_DOSSIER", "DOSSIER_STATUS", "DQ_SCORE", "BASE_CERTIFIABLE",
                        "BASE_CERTIFICATION_REASONS", "CTS_NOM_PRENOM_TRAVAILLEUR", "SIEGE_RACINE",
                        "NUMERO_DOMICILIATION_PROPOSE", "CARTHAGO_MATCH_STATUS", "DOM_COMPTE_LOCAL_STATUS",
                        "NB_MOTIFS_CLIENT_PROPOSES"] if c in DOSSIERS.columns]
    if "FICHIER" not in DOSSIERS.columns:
        st.info("Aucun dossier dans le classeur.")
        st.stop()
    view = DOSSIERS[cols].merge(PROG[["FICHIER", "RESTANT", "STATUT_VALIDATION"]], on="FICHIER", how="left")
    view["STATUT_VALIDATION"] = view["STATUT_VALIDATION"].fillna("AUCUNE_LIGNE")
    f1, f2 = st.columns(2)
    stv = f1.multiselect("Statut validation", sorted(view["STATUT_VALIDATION"].unique()))
    q = f2.text_input("Recherche (fichier, nom, siège)")
    if stv:
        view = view[view["STATUT_VALIDATION"].isin(stv)]
    if q:
        view = view[view.astype(str).apply(lambda r: q.lower() in " ".join(r).lower(), axis=1)]
    st.dataframe(view, hide_index=True, **ui.W, height=480)

# ------------------------------------------------------------------ ③ validation
with tab_val:
    bks = [b for b in domvalid.backups(P.validation_xlsx) if b.stat().st_mtime < MT]
    if bks:
        with st.expander("Reporter les décisions d'un classeur précédent (après un nouveau run Partie 2)"):
            bk = st.selectbox("Classeur précédent", bks, format_func=lambda b: f"{b.name} ({ui.mtime(b)})")
            todo = domvalid.carry_over(bk, P.validation_xlsx)
            st.caption(f"{len(todo)} décision(s) reportable(s) — uniquement les lignes identiques "
                       "(fichier, champ, page, valeur RAW) encore non décidées.")
            if len(todo) and st.button("Reporter ces décisions"):
                res = domvalid.save_decisions(P.validation_xlsx, todo, expected_mtime=MT)
                audit(P.audit_log, "DOM_VALIDATION_REPORT", current_user(), source=bk.name, n=len(res["changes"]))
                st.cache_data.clear()
                st.rerun()
    if MANUAL.empty:
        st.success("Aucune ligne à valider manuellement.")
    else:
        order = PROG.set_index("FICHIER")
        files = list(PROG["FICHIER"])
        lab = {f: f"{f} — {order.loc[f, 'RESTANT']} à décider" + (" · REJETÉ" if order.loc[f, "REJETEES"] else "")
               for f in files}
        left, right = st.columns([3, 2])
        with left:
            only_open = st.toggle("Seulement les dossiers non terminés", value=True)
            cand = [f for f in files if not only_open or order.loc[f, "STATUT_VALIDATION"] == "EN_COURS"] or files
            fichier = st.selectbox("Dossier", cand, format_func=lambda f: lab[f])
            sub = MANUAL[MANUAL["FICHIER"] == fichier].copy()
            show = [c for c in ["_ROW", "CHAMP", "RAW", "VALEUR_PROPOSEE", "DECISION_MANUELLE", "VALEUR_VALIDEE",
                                "COMMENTAIRE", "NORMALIZED", "NIVEAU_CONFIDENCE", "CONFIDENCE_QUALITE", "PAGE",
                                "TYPE_DOCUMENT", "CONTEXTE_VALIDATION", "SOURCE_PROPOSITION"] if c in sub.columns]
            edited = st.data_editor(
                sub[show], hide_index=True, **ui.W, key=f"ed_{fichier}",
                disabled=[c for c in show if c not in domvalid.EDITABLE],
                column_config={
                    "_ROW": st.column_config.NumberColumn("Ligne", width="small"),
                    "DECISION_MANUELLE": st.column_config.SelectboxColumn("Décision", options=domvalid.DECISIONS),
                    "VALEUR_VALIDEE": st.column_config.TextColumn("Valeur validée"),
                    "COMMENTAIRE": st.column_config.TextColumn("Commentaire / motif"),
                    "CONTEXTE_VALIDATION": st.column_config.TextColumn("Contexte", width="large"),
                })
            b1, b2, _ = st.columns([1.3, 1.6, 2])
            if b1.button("💾 Enregistrer", type="primary"):
                full = sub.copy()
                for c in domvalid.EDITABLE:
                    full[c] = edited[c].values
                errs = domvalid.check_decisions(full)
                if errs:
                    st.error("\n".join(errs))
                else:
                    try:
                        res = domvalid.save_decisions(P.validation_xlsx, full, expected_mtime=MT)
                        audit(P.audit_log, "DOM_VALIDATION", current_user(), fichier=fichier,
                              changes=res["changes"], backup=res["backup"])
                        st.cache_data.clear()
                        st.success(f"{len(res['changes'])} modification(s) enregistrée(s).")
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))
            if b2.button("✔ Accepter les propositions restantes"):
                full = sub.copy()
                for c in domvalid.EDITABLE:
                    full[c] = edited[c].values
                todo = full["DECISION_MANUELLE"].map(is_blank) & ~full["VALEUR_PROPOSEE"].map(is_blank) \
                    if "VALEUR_PROPOSEE" in full.columns else pd.Series(False, index=full.index)
                full.loc[todo, "DECISION_MANUELLE"] = "VALIDEE"
                errs = domvalid.check_decisions(full)
                if errs:
                    st.error("\n".join(errs))
                else:
                    try:
                        res = domvalid.save_decisions(P.validation_xlsx, full, expected_mtime=MT)
                        audit(P.audit_log, "DOM_VALIDATION_PROPOSITIONS", current_user(), fichier=fichier,
                              changes=res["changes"])
                        st.cache_data.clear()
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))
            st.caption("Règles : CORRIGEE exige une valeur validée · REJETEE exige un motif · "
                       "un rejet exclut le dossier du Planning TL.")
        with right:
            rows = list(sub["_ROW"])
            r_sel = st.selectbox("Ligne à visualiser", rows,
                                 format_func=lambda r: f"L{r} — {sub.set_index('_ROW').loc[r, 'CHAMP']}")
            page = sub.set_index("_ROW").loc[r_sel, "PAGE"] if "PAGE" in sub.columns else 1
            ui.pdf_viewer(P.dom_in, fichier, page, key=f"pg_{fichier}_{r_sel}")

# ------------------------------------------------------------------ ④ contexte
with tab_ctx:
    names = domvalid.sheet_names(P.validation_xlsx)
    sh = st.selectbox("Feuille", [n for n in domvalid.CONTEXT_SHEETS if n in names])
    df = domvalid.load_sheet(P.validation_xlsx, sh)
    ff = st.selectbox("Filtrer sur un dossier", ["(tous)"] + sorted(DOSSIERS["FICHIER"].astype(str)), key="ctxf")
    if ff != "(tous)" and "FICHIER" in df.columns:
        df = df[df["FICHIER"].astype(str) == ff]
    st.dataframe(df, hide_index=True, **ui.W, height=520)
    st.download_button("Télécharger le classeur de validation", P.validation_xlsx.read_bytes(),
                       file_name=P.validation_xlsx.name)

