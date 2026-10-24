import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from tlone import domvalid, matrice, planning, transfers, ui, ui_matrice  # noqa: E402
from tlone.common import audit, current_user, to_excel_bytes  # noqa: E402

s = ui.setup("Planning TL")
P = s.paths
ui.hero("Échéancier des transferts (Planning TL)",
        "Pour chaque domiciliation validée : le montant autorisé mois par mois, du début à la fin du contrat, avec les "
        "augmentations et le prorata des mois partiels. Ce qui a déjà été transféré et ce qui reste à régulariser.",
        ["CTS = référence", "P1 / P2", "Planning × base RH"], etape="Étape 2 sur 5",
        expert_subtitle="Échéancier de chaque domiciliation, du début à la fin du contrat (CTS) : part transférable par "
                        "mois (prorata P1 / P2), augmentations, montant domicilié, reliquats à régulariser.")

tab_gen, tab_view, tab_dom, tab_rh, tab_rej = ui.onglets(
    [("① Mettre à jour", False), ("② Échéancier", False), ("③ Par salarié", False), ("④ Contrôle base RH", False),
     ("Rejets & audit", True)])

with tab_gen:
    ok = True
    if not P.validation_xlsx.exists():
        st.error("Classeur de validation DOM absent (Module 1).")
        ok = False
    _req = []
    if P.validation_xlsx.exists():
        try:
            _d = domvalid.load_sheet(P.validation_xlsx, domvalid.DOSSIERS_SHEET)
            if "AUGMENTATION_YEAR" in _d:
                _req = pd.to_numeric(_d["AUGMENTATION_YEAR"], errors="coerce").dropna().astype(int).unique().tolist()
        except Exception:  # noqa: BLE001
            _req = []
    _absent = not P.param_aug_xlsx.exists()
    with st.expander("📅 Calendrier des augmentations"
                     + (" — à renseigner avant la mise à jour" if _absent else ""), expanded=_absent):
        ui.calendrier_augmentations(P, key="pa_plan", annees_requises=_req)
    if _absent:
        st.error("Renseignez le calendrier des augmentations ci-dessus (une ligne par année) puis enregistrez.")
        ok = False
    if ok:
        man = domvalid.load_manual(P.validation_xlsx)
        prog = domvalid.progress(man)
        restant = int(prog["RESTANT"].sum()) if not prog.empty else 0
        c = st.columns(3)
        if ui.expert():
            c[0].metric("Lignes non décidées", restant)
            c[1].metric("Dossiers en cours de validation", int((prog["STATUT_VALIDATION"] == "EN_COURS").sum())
                        if not prog.empty else 0)
        c[2 if ui.expert() else 0].metric("Dernière mise à jour", ui.mtime(P.planning_csv))
        _lot, _ms = ui_matrice.load(P)
        _app = matrice.planning_rows(_ms)
        _val = {m["fichier"] for m in _ms if m["decision"] and m["decision"]["action"] == "VALIDE"}
        _rej = {m["fichier"] for m in _ms if m["decision"] and m["decision"]["action"] == "REJETE"}
        st.markdown(f"Matrice de validation : **{len(_val)}** dossier(s) validé(s), **{len(_rej)}** rejeté(s), "
                    f"**{len(_ms) - len(_val) - len(_rej)}** non traité(s).")
        st.info("Seuls les dossiers **validés dans la matrice DOM** sont planifiés, avec leurs valeurs de référence "
                "(date de début, date de fin, durée, part transférable…) : du début à la fin du contrat validé. "
                "Un dossier non validé ou rejeté n'entre pas dans le Planning"
                + (" (onglet Rejets & audit)." if ui.expert() else " : la raison est indiquée ci-dessous."))
        seul = True
        if P.planning_csv.exists() and P.dom_journal.exists() and \
                P.dom_journal.stat().st_mtime > P.planning_csv.stat().st_mtime:
            st.warning("Des dossiers ont été validés ou modifiés depuis la dernière mise à jour : cliquez sur "
                       "« Mettre à jour l'échéancier ».")
        excl = st.toggle("Exclure les dossiers dont la validation n'est pas terminée", value=True,
                         help="Désactivé = comportement exact du notebook Planning_TL_V15A (une ligne sans "
                              "décision garde la valeur extraite).") if ui.expert() else True
        if restant and not excl:
            st.warning(f"{restant} ligne(s) sans décision : leurs valeurs OCR seront utilisées telles quelles.")
        if st.button("▶ Mettre à jour l'échéancier", type="primary"):
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
    if P.planning_xlsx.exists():
        try:
            _rj = pd.read_excel(P.planning_xlsx, sheet_name="REJETS_PLANNING")
        except Exception:  # noqa: BLE001  ancien classeur sans la feuille
            _rj = pd.DataFrame()
        if not _rj.empty:
            with st.expander(f"⚠️ {len(_rj)} dossier(s) non planifié(s) — pourquoi ?", expanded=not ui.expert()):
                st.dataframe(pd.DataFrame({"Dossier": _rj["FICHIER"],
                                           "Raison": _rj["MOTIF"].map(planning.motif_lisible)}),
                             hide_index=True, **ui.W)

PL = planning.load_planning(P.planning_csv)
if PL.empty:
    for t in (tab_view, tab_dom, tab_rh, tab_rej):
        if t is None:
            continue
        with t:
            st.info("Aucun planning généré.")
    st.stop()

from tlone import execution as ex  # noqa: E402

# Planning complet (début → fin du CTS) + exécutions réelles : débits Atlas (page 4) et registre TL-One
_hf, _hd, _hr, _he, _hk = ui.historique_data(P, s)
CONS = ex.suivi_planning(PL, transfers.load_registre(P.registre_csv), _hd.get("trade"), _hd.get("atlas"),
                         tol=s.tolerance_montant_dzd)

with tab_view:
    HV, h_lab = ui.horizon_planning(CONS, "pl_view")
    m = st.columns(5)
    m[0].metric("Domiciliations", HV["DOM_ID"].nunique())
    m[1].metric("Périodes", len(HV))
    m[2].metric("Montant théorique (DZD)", ui.fmt_dzd(HV["MONTANT_MAX_THEORIQUE"].sum()))
    m[3].metric("Déjà transféré (DZD)", ui.fmt_dzd(HV["MONTANT_TRANSFERE"].sum()))
    m[4].metric("Reliquat à régulariser (DZD)", ui.fmt_dzd(HV["RELIQUAT"].sum()))
    st.caption(f"Affichage : {h_lab}. Chaque DOM validée va de sa date de début à sa date de fin de référence "
               "(matrice DOM).")
    _cd = None
    _ctl_path = P.planning_xlsx
    if _ctl_path.exists():
        try:
            _cd = pd.read_excel(_ctl_path, sheet_name="CONTROLE_DUREE")
        except Exception:  # noqa: BLE001  ancien classeur sans la feuille
            _cd = None
    if _cd is not None and not _cd.empty:
        _bad = _cd[_cd["CONTROLE_DUREE"].astype(str) != "OK"]
        if not _bad.empty:
            st.warning(f"{len(_bad)} domiciliation(s) dont le nombre de mois planifiés ≠ durée de référence, ou sans "
                       "contrat initial validé :")
            st.dataframe(_bad.drop(columns=["DOM_ID"]), hide_index=True, **ui.W)
    if _hd.get("atlas") is None:
        st.caption("Historique Atlas non chargé (page 4) : « transféré » ne compte que le registre TL-One.")
    f = st.columns(4)
    mois = f[0].multiselect("Mois", sorted(HV["MOIS_BASE"].unique()))
    stat = f[1].multiselect("Statut période", sorted(HV["STATUT_PERIODE"].unique()),
                            format_func=lambda x: ex.ETAT_PERIODE.get(x, x))
    typ = f[2].multiselect("Version", sorted(HV["TYPE_VERSION"].unique()))
    q = f[3].text_input("Travailleur / siège / DOM")
    v = HV
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
            "SOLDE_RESTANT", "RELIQUAT", "STATUT_PERIODE", "TL_EXECUTES", "TL_SAISIS", "TL_ANOMALIE",
            "DATE_DEBUT_REFERENCE", "DATE_FIN_REFERENCE", "DUREE_REFERENCE_MOIS", "BASE_DATES"]
    if not ui.expert():
        cols = ["PERIODE_TL", "NOM_TRAVAILLEUR", "SIEGE_RACINE", "NUMERO_DOMICILIATION", "TYPE_VERSION",
                "DATE_DEBUT_SEGMENT", "DATE_FIN_SEGMENT", "MONTANT_MAX_THEORIQUE", "MONTANT_TRANSFERE", "RELIQUAT",
                "STATUT_PERIODE"]
    cols = [c for c in cols if c in v.columns]       # un ancien Planning (avant le 23/10/2026) n'a pas les colonnes contrat
    _cfg = {c: st.column_config.NumberColumn(ui.COL_FR.get(c, c) if not ui.expert() else c, format="%.2f") for c in
            ("PART_TRANSFERABLE_CTS", "MONTANT_MAX_THEORIQUE", "MONTANT_TRANSFERE", "SOLDE_RESTANT", "RELIQUAT")}
    if not ui.expert():
        _cfg.update({c: st.column_config.Column(ui.COL_FR[c]) for c in cols if c in ui.COL_FR and c not in _cfg})
    st.dataframe(v[cols].assign(STATUT_PERIODE=v["STATUT_PERIODE"].map(lambda x: ex.ETAT_PERIODE.get(x, x)),
                                TYPE_VERSION=v["TYPE_VERSION"].map(lambda x: ui.VERSION_FR.get(x, x))
                                if not ui.expert() else v["TYPE_VERSION"]),
                 hide_index=True, **ui.W, height=520, column_config=_cfg)
    st.download_button("Télécharger le Planning (Excel, sélection)", to_excel_bytes({"Planning_TL": v}),
                       file_name="Planning_TL_selection.xlsx")
    if P.planning_xlsx.exists():
        st.download_button("Télécharger le classeur Planning complet", P.planning_xlsx.read_bytes(),
                           file_name=P.planning_xlsx.name)

with tab_dom:
    doms = (CONS.groupby(["DOM_ID", "NOM_TRAVAILLEUR", "NUMERO_DOMICILIATION", "SIEGE_RACINE"], dropna=False)
            .agg(PERIODES=("PERIODE_ID", "count"), DEBUT=("DATE_DEBUT_SEGMENT", "min"), FIN=("DATE_FIN_SEGMENT", "max"),
                 AUGMENTATIONS=("NOMBRE_TOTAL_AUGMENTATIONS", "max"), MONTANT_DOMICILIE=("MONTANT_MAX_THEORIQUE", "sum"),
                 TRANSFERE=("MONTANT_TRANSFERE", "sum")).reset_index())
    doms["SOLDE_DOM"] = (doms["MONTANT_DOMICILIE"] - doms["TRANSFERE"]).round(2)
    _fr = (lambda c: c) if ui.expert() else (lambda c: ui.COL_FR.get(c, c))
    st.dataframe(doms.drop(columns=["DOM_ID"]).rename(columns=_fr), hide_index=True, **ui.W,
                 column_config={_fr(c): st.column_config.NumberColumn(format="%.2f")
                                for c in ("MONTANT_DOMICILIE", "TRANSFERE", "SOLDE_DOM")})
    sel = st.selectbox("Détail d'une domiciliation" if ui.expert() else "Voir le détail d'un salarié", doms["DOM_ID"],
                       format_func=lambda d: " · ".join(str(x) for x in doms.set_index("DOM_ID").loc[
                           d, ["NOM_TRAVAILLEUR", "NUMERO_DOMICILIATION"]]))
    det, _ = ui.horizon_planning(CONS[CONS["DOM_ID"] == sel], "pl_dom")
    det = det.set_index("PERIODE_TL")
    st.bar_chart(det[["MONTANT_TRANSFERE", "SOLDE_RESTANT"]], stack=True, height=280)
    st.caption("Une marche dans la hauteur des barres = augmentation ; les barres courtes en début/fin = "
               "périodes partielles (prorata).")
    st.dataframe(det.reset_index()[["PERIODE_TL", "TYPE_VERSION", "NUMERO_AUGMENTATION", "MONTANT_MAX_THEORIQUE",
                                    "MONTANT_TRANSFERE", "SOLDE_RESTANT", "STATUT_PERIODE", "FICHIER_SOURCE"]],
                 hide_index=True, **ui.W)

with tab_rh:
    from tlone import referentiels, rh
    _rhdf = referentiels.load_all(P)["rh"]
    st.caption("Base RH du mois face au Planning : la DOM couvre-t-elle chaque PART (P1 ancien contrat, P2 nouveau) "
               "et la part transférable du Planning est-elle celle de la RH ? Dépôt de la base RH : page Transferts OV, "
               "onglet ② Référentiels du mois.")
    _mois_rh = sorted(_rhdf["MOIS"].dropna().unique()) if not _rhdf.empty else []
    if _mois_rh:
        _m_rh = st.selectbox("Mois de la base RH", _mois_rh[::-1], key="pl_rh_m")
        _rhdf = _rhdf[_rhdf["MOIS"] == _m_rh]
    _pv = rh.planning_vs_rh(PL, _rhdf)
    if _pv.empty:
        st.info("Aucune base RH déposée.")
    else:
        _c = _pv["STATUT"].value_counts()
        _k = st.columns(4)
        for _i, (_code, _lab) in enumerate((("OK", "✅ Conformes"), ("ECART", "🟠 Écarts"),
                                           ("PERIODE_NON_DOMICILIEE", "🗓️ Période non domiciliée"),
                                           ("DOM_ABSENTE", "🔴 DOM absente"))):
            _k[_i].metric(_lab, int(_c.get(_code, 0)))
        from tlone.ui_referentiels import _apercu
        _apercu(_pv, "pl_pv", None, height=420)

if tab_rej:
    with tab_rej:
        if P.planning_xlsx.exists():
            _xl = pd.ExcelFile(P.planning_xlsx)
            for sh in ("CONTROLE_DUREE", "REJETS_PLANNING", "CORRECTIONS_APPLIQUEES", "REGLES"):
                if sh in _xl.sheet_names:
                    st.subheader(sh)
                    st.dataframe(pd.read_excel(_xl, sheet_name=sh), hide_index=True, **ui.W)
