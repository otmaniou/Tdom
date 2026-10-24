import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from tlone import domvalid, matrice, ui, ui_matrice  # noqa: E402
from tlone.common import audit, current_user, is_blank  # noqa: E402

s = ui.setup("Contrôles DOM")
P = s.paths
ui.hero("Domiciliations (DOM)",
        "Déposez les dossiers de domiciliation : l'IA lit chaque pièce (DOM, CTS, contrat, titre de travail), TL-One les "
        "compare entre elles, à CarthagoDom et à la base RH. Vous ne regardez que les cases en rouge.",
        ["Lecture IA des scans", "Matrice pièces × données", "Validation tracée"], etape="Étape 1 sur 5",
        expert_subtitle="Dossiers scannés (DOM, CTR, CTS, permis) lus par l'IA puis contrôlés pièce par pièce : identité, "
                        "dates, salaire, part transférable, compte (clé Modulo 97), n° de domiciliation (CarthagoDom).")
ui.guide([("Déposer", "un dossier ou des centaines de PDF"), ("Faire lire par l'IA", "lecture et contrôles automatiques"),
          ("Vérifier", "uniquement les cases en rouge"), ("Valider", "un par un ou toute une sélection")])

tab_run, tab_dash, tab_val, tab_ctx, tab_param = ui.onglets(
    [("① Déposer et lire", False), ("② Vérifier et valider", False), ("Classeur Partie 2", True),
     ("Contrôles & anomalies", True), ("Paramètres", True)])

# ------------------------------------------------------------------ ① traitement
with tab_run:
    if not ui.expert():
        ui.lecture_panel(s, "dom_extract", "Dossiers de domiciliation",
                         "Les documents déjà lus ne sont jamais relus : vous pouvez déposer un seul dossier ou un lot "
                         "complet. Après la lecture, les contrôles démarrent seuls.", P.dom_in, "up_dom_simple",
                         ensuite="dom_post")
    c1, c2 = st.columns(2) if ui.expert() else (None, st.expander(
        f"Référentiel CarthagoDom — mis à jour le {ui.mtime(P.carthago_xlsx)}"))
    if c1 is not None:
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
    if ui.expert():
        ui.job_panel(s, "dom_extract", "Partie 1 V15-A : orientation, classification, extraction 99 champs, "
                                   "recovery 2400 px → JSON RAW par dossier. Reprise sur checkpoint (RESUME).")
        ui.job_panel(s, "dom_post", "Partie 2 V15-A : normalisation, DQ, confidence, rapprochement Carthago, "
                                    "Modulo 97 → classeur de validation. ⚠️ Régénère le classeur : les décisions "
                                    "déjà saisies dans l'app sont à reporter (une sauvegarde est conservée).")

# ------------------------------------------------------------------ ⑤ paramètres
if tab_param:
    with tab_param:
        st.subheader("Sources de référence")
        st.caption("Pour chaque donnée, la pièce qui fait foi. Les autres pièces sont comparées à elle ; la valeur "
                   "retenue part au Planning TL. Le valideur peut changer de source pour un dossier donné (tracé).")
        srcs = matrice.sources_table(P.sources_reference_xlsx)
        src_ed = st.data_editor(srcs, hide_index=True, key="src_ed", disabled=["LIGNE", "DONNEE", "SOURCES_POSSIBLES",
                                                                             "ALIMENTE_LE_PLANNING"],
                                column_config={"SOURCE_REFERENCE": st.column_config.SelectboxColumn(
                                    "Source de référence", options=matrice.COLS, required=True)})
        if st.button("Enregistrer les sources de référence"):
            bad = [r["DONNEE"] for _, r in src_ed.iterrows()
                   if r["SOURCE_REFERENCE"] not in r["SOURCES_POSSIBLES"].split(", ")]
            if bad:
                st.error("Source impossible pour : " + ", ".join(bad))
            else:
                from tlone.common import backup
                backup(P.sources_reference_xlsx)
                P.sources_reference_xlsx.parent.mkdir(parents=True, exist_ok=True)
                src_ed[["LIGNE", "DONNEE", "SOURCE_REFERENCE"]].to_excel(P.sources_reference_xlsx, index=False)
                audit(P.audit_log, "PARAM_SOURCES_REFERENCE", current_user(),
                      valeurs=dict(zip(src_ed["LIGNE"], src_ed["SOURCE_REFERENCE"])))
                st.success("Sources de référence enregistrées.")
        st.divider()
        st.subheader("Calendrier des augmentations")
        ui.calendrier_augmentations(P, key="pa_ed")

if not P.validation_xlsx.exists():
    for t in (tab_dash, tab_val, tab_ctx):
        if t is None:
            continue
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

# ------------------------------------------------------------------ ② dossiers & validation (matrice)
with tab_dash:
    ui_matrice.render(P)

# ------------------------------------------------------------------ ③ validation
if tab_val:
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
if tab_ctx:
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

