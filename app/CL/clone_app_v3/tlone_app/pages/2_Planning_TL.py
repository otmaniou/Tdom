import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from tlone import domvalid, matrice, planning, transfers, ui, ui_matrice  # noqa: E402
from tlone.common import audit, current_user, to_excel_bytes  # noqa: E402

s = ui.setup("Planning TL")
P = s.paths
st.title("2 · Planning TL")
st.caption("Échéancier mensuel des transferts par domiciliation — CTS corrigé = référence ; "
           "augmentation effective au 1er du mois paramétré ; prorata jours/mois (P1/P2).")

tab_gen, tab_view, tab_dom, tab_rej = st.tabs(["① Générer", "② Planning", "③ Par domiciliation", "④ Rejets & audit"])

with tab_gen:
    ok = True
    if not P.validation_xlsx.exists():
        st.error("Classeur de validation DOM absent (Module 1).")
        ok = False
    if not P.param_aug_xlsx.exists():
        st.error("Calendrier des augmentations absent (Module 1 › Paramètres).")
        ok = False
    if ok:
        man = domvalid.load_manual(P.validation_xlsx)
        prog = domvalid.progress(man)
        restant = int(prog["RESTANT"].sum()) if not prog.empty else 0
        c = st.columns(3)
        c[0].metric("Lignes non décidées", restant)
        c[1].metric("Dossiers en cours de validation", int((prog["STATUT_VALIDATION"] == "EN_COURS").sum())
                    if not prog.empty else 0)
        c[2].metric("Dernier planning", ui.mtime(P.planning_csv))
        _lot, _ms = ui_matrice.load(P)
        _app = matrice.planning_rows(_ms)
        _val = {m["fichier"] for m in _ms if m["decision"] and m["decision"]["action"] == "VALIDE"}
        _rej = {m["fichier"] for m in _ms if m["decision"] and m["decision"]["action"] == "REJETE"}
        st.markdown(f"Matrice de validation : **{len(_val)}** dossier(s) validé(s), **{len(_rej)}** rejeté(s), "
                    f"**{len(_ms) - len(_val) - len(_rej)}** non traité(s).")
        seul = st.toggle("Planifier uniquement les dossiers validés dans la matrice", value=True,
                         help="Les valeurs retenues dans la matrice (source de référence choisie, corrections) "
                              "remplacent les valeurs extraites.")
        excl = st.toggle("Exclure les dossiers dont la validation n'est pas terminée", value=True,
                         help="Désactivé = comportement exact du notebook Planning_TL_V15A (une ligne sans "
                              "décision garde la valeur extraite).")
        if restant and not excl:
            st.warning(f"{restant} ligne(s) sans décision : leurs valeurs OCR seront utilisées telles quelles.")
        if st.button("▶ Générer le Planning TL", type="primary"):
            dos = domvalid.load_sheet(P.validation_xlsx, domvalid.DOSSIERS_SHEET)
            man_raw = matrice.merge_manual(domvalid.load_sheet(P.validation_xlsx, domvalid.MANUAL_SHEET), _app)
            pa = pd.read_excel(P.param_aug_xlsx, dtype=object)
            try:
                res = planning.build_planning(dos, man_raw, pa, exclure_validation_incomplete=excl,
                                              fichiers_valides=_val if seul else None)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Échec : {exc}")
                st.stop()
            if res["Planning_TL"].empty:
                st.warning("Aucune période générée : aucun dossier planifiable"
                           + (" (aucun dossier validé dans la matrice)" if seul and not _val else "")
                           + ". Le planning précédent est conservé. Voir les rejets ci-dessous.")
                st.dataframe(res["REJETS_PLANNING"], hide_index=True, **ui.W)
            elif res["_dq"]:
                st.error(f"Contrôles DQ du planning en échec : {res['_dq']} — export non effectué.")
            else:
                from tlone.common import backup
                backup(P.planning_xlsx)
                planning.export(res, P.planning_xlsx, P.planning_csv)
                audit(P.audit_log, "PLANNING_GENERATION", current_user(), periodes=len(res["Planning_TL"]),
                      versions=len(res["BASE_VERSIONS_CTS"]), rejets=len(res["REJETS_PLANNING"]),
                      exclusion_incomplets=excl)
                st.success(f"Planning généré : {len(res['Planning_TL'])} périodes, "
                           f"{len(res['BASE_VERSIONS_CTS'])} versions CTS, {len(res['REJETS_PLANNING'])} rejet(s).")

PL = planning.load_planning(P.planning_csv)
if PL.empty:
    for t in (tab_view, tab_dom, tab_rej):
        with t:
            st.info("Aucun planning généré.")
    st.stop()

CONS = transfers.consumption(PL, transfers.load_registre(P.registre_csv), tol=s.tolerance_montant_dzd)

with tab_view:
    m = st.columns(4)
    m[0].metric("Domiciliations", PL["DOM_ID"].nunique())
    m[1].metric("Périodes", len(PL))
    m[2].metric("Montant théorique total (DZD)", ui.fmt_dzd(PL["MONTANT_MAX_THEORIQUE"].sum()))
    m[3].metric("Déjà transféré (DZD)", ui.fmt_dzd(CONS["MONTANT_TRANSFERE"].sum()))
    f = st.columns(4)
    mois = f[0].multiselect("Mois", sorted(CONS["MOIS_BASE"].unique()))
    stat = f[1].multiselect("Statut période", sorted(CONS["STATUT_PERIODE"].unique()))
    typ = f[2].multiselect("Version", sorted(CONS["TYPE_VERSION"].unique()))
    q = f[3].text_input("Travailleur / siège / DOM")
    v = CONS
    if mois:
        v = v[v["MOIS_BASE"].isin(mois)]
    if stat:
        v = v[v["STATUT_PERIODE"].isin(stat)]
    if typ:
        v = v[v["TYPE_VERSION"].isin(typ)]
    if q:
        ql = q.lower()
        v = v[v[["NOM_TRAVAILLEUR", "SIEGE_RACINE", "NUMERO_DOMICILIATION"]].astype(str)
              .apply(lambda r: ql in " ".join(r).lower(), axis=1)]
    cols = ["PERIODE_TL", "NOM_TRAVAILLEUR", "SIEGE_RACINE", "NUMERO_DOMICILIATION", "TYPE_VERSION",
            "NUMERO_AUGMENTATION", "DATE_DEBUT_SEGMENT", "DATE_FIN_SEGMENT", "NB_JOURS_SEGMENT",
            "COEFFICIENT_PRORATA", "PART_TRANSFERABLE_CTS", "MONTANT_MAX_THEORIQUE", "MONTANT_TRANSFERE",
            "SOLDE_RESTANT", "STATUT_PERIODE"]
    st.dataframe(v[cols], hide_index=True, **ui.W, height=520,
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in
                                ("PART_TRANSFERABLE_CTS", "MONTANT_MAX_THEORIQUE", "MONTANT_TRANSFERE", "SOLDE_RESTANT")})
    st.download_button("Télécharger le Planning (Excel, sélection)", to_excel_bytes({"Planning_TL": v}),
                       file_name="Planning_TL_selection.xlsx")
    st.download_button("Télécharger le classeur Planning complet", P.planning_xlsx.read_bytes(),
                       file_name=P.planning_xlsx.name)

with tab_dom:
    doms = (CONS.groupby(["DOM_ID", "NOM_TRAVAILLEUR", "NUMERO_DOMICILIATION", "SIEGE_RACINE"], dropna=False)
            .agg(PERIODES=("PERIODE_ID", "count"), DEBUT=("DATE_DEBUT_SEGMENT", "min"), FIN=("DATE_FIN_SEGMENT", "max"),
                 AUGMENTATIONS=("NOMBRE_TOTAL_AUGMENTATIONS", "max"), MONTANT_DOMICILIE=("MONTANT_MAX_THEORIQUE", "sum"),
                 TRANSFERE=("MONTANT_TRANSFERE", "sum")).reset_index())
    doms["SOLDE_DOM"] = (doms["MONTANT_DOMICILIE"] - doms["TRANSFERE"]).round(2)
    st.dataframe(doms.drop(columns=["DOM_ID"]), hide_index=True, **ui.W,
                 column_config={c: st.column_config.NumberColumn(format="%.2f")
                                for c in ("MONTANT_DOMICILIE", "TRANSFERE", "SOLDE_DOM")})
    sel = st.selectbox("Détail d'une domiciliation", doms["DOM_ID"],
                       format_func=lambda d: " · ".join(str(x) for x in doms.set_index("DOM_ID").loc[
                           d, ["NOM_TRAVAILLEUR", "NUMERO_DOMICILIATION"]]))
    det = CONS[CONS["DOM_ID"] == sel].set_index("PERIODE_TL")
    st.bar_chart(det[["MONTANT_TRANSFERE", "SOLDE_RESTANT"]], stack=True, height=280)
    st.caption("Une marche dans la hauteur des barres = augmentation ; les barres courtes en début/fin = "
               "périodes partielles (prorata).")
    st.dataframe(det.reset_index()[["PERIODE_TL", "TYPE_VERSION", "NUMERO_AUGMENTATION", "MONTANT_MAX_THEORIQUE",
                                    "MONTANT_TRANSFERE", "SOLDE_RESTANT", "STATUT_PERIODE", "FICHIER_SOURCE"]],
                 hide_index=True, **ui.W)

with tab_rej:
    if P.planning_xlsx.exists():
        for sh in ("REJETS_PLANNING", "CORRECTIONS_APPLIQUEES", "REGLES"):
            st.subheader(sh)
            st.dataframe(pd.read_excel(P.planning_xlsx, sheet_name=sh), hide_index=True, **ui.W)
