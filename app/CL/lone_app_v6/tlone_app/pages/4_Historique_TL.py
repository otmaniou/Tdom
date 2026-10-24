import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from tlone import execution as ex  # noqa: E402
from tlone import historique as h  # noqa: E402
from tlone import planning, transfers, ui  # noqa: E402
from tlone.common import audit, current_user, to_excel_bytes  # noqa: E402

s = ui.setup("Historique TL")
P = s.paths
ui.hero("4 · TL à exécuter & historique", "CarthagoTrade × Atlas : TL saisis à exécuter (blocages, solde, doublons, "
        "compléments), TL réellement exécutés (débit Atlas), anomalies (double débit, rejeté débité…), reliquats.",
        ["Blocage : solde − Σ(TL + 5 000) ≥ 0", "Seul le débit Atlas fait foi", "Fichier employeur"])

GRAV = {"CRITIQUE": "🔴 Critique", "ELEVEE": "🟠 Élevée", "A_VERIFIER": "🟡 À vérifier"}
tab_files, tab_exe, tab_an, tab_plan, tab_reg, tab_hist, tab_per, tab_bs = st.tabs(
    ["① Fichiers", "② TL à exécuter", "③ Anomalies", "④ Planning × TL", "⑤ Régularisation (motifs)",
     "⑥ Historique rapproché", "⑦ Périodes par client", "⑧ Blocages & soldes"])

with tab_files:
    st.caption("Déposez les exports tels qu'ils sortent des systèmes ; le type est reconnu par le nom : "
               "`Historique_mouvement_altas-…xlsx`, `Transfert libre -….xls`, `Blocage-….xlsx`, `comptes_solde-….xlsx`. "
               "Le plus récent de chaque type est utilisé.")
    ups = st.file_uploader("Exports", type=["xlsx", "xls", "csv"], accept_multiple_files=True, key="hist_up")
    if ups and st.button(f"Enregistrer {len(ups)} fichier(s)", type="primary"):
        P.historique_dir.mkdir(parents=True, exist_ok=True)
        ko = []
        for u in ups:
            if not h.kind_of(u.name):
                ko.append(u.name)
                continue
            (P.historique_dir / Path(u.name).name).write_bytes(u.getbuffer())
            audit(P.audit_log, "HISTORIQUE_UPLOAD", current_user(), fichier=u.name)
        if ko:
            st.warning("Type non reconnu (nom de fichier) : " + ", ".join(ko))
        st.rerun()
    files = h.latest(P.historique_dir)
    st.dataframe(pd.DataFrame([{"Type": h.LABEL[k], "Fichier utilisé": files[k].name if k in files else "— absent",
                                "Reçu le": ui.mtime(files[k]) if k in files else ""} for k in h.LABEL]),
                 hide_index=True, **ui.W)
    with st.container(border=True):
        st.markdown("**Extractions OV des mois passés** (`audit_transferts_*.xlsx` des anciens lots)")
        st.caption("Elles servent à la régularisation : savoir pour chaque période non transférée si le dossier avait "
                   "été scanné et ce qu'il est devenu. Les ATF et autorisations des mois passés se déposent dans "
                   "Transferts OV › Référentiels du mois (un fichier par mois).")
        hov = P.data_root / "historique_ov"
        up2 = st.file_uploader("Extractions OV passées", type=["xlsx"], accept_multiple_files=True, key="hist_ov_up")
        if up2 and st.button(f"Enregistrer {len(up2)} extraction(s)", key="hist_ov_btn"):
            hov.mkdir(parents=True, exist_ok=True)
            for u in up2:
                nom = Path(u.name).name if Path(u.name).name.startswith("audit_transferts_") else f"audit_transferts_{Path(u.name).name}"
                (hov / nom).write_bytes(u.getbuffer())
                audit(P.audit_log, "HISTORIQUE_OV_UPLOAD", current_user(), fichier=u.name)
            st.cache_data.clear()
            st.rerun()
        st.caption(f"{len(list(hov.glob('audit_transferts_*.xlsx'))) if hov.exists() else 0} extraction(s) passée(s) déposée(s).")

files = h.latest(P.historique_dir)
if "trade" not in files and "atlas" not in files:
    for t in (tab_exe, tab_an, tab_plan, tab_reg, tab_hist, tab_per, tab_bs):
        with t:
            st.info("Déposez au moins l'historique Atlas ou l'export CarthagoTrade (onglet ① Fichiers).")
    st.stop()


_files, data, res, errs, _hk = ui.historique_data(P, s)
for e in errs:
    st.error(e)
an, hist = res["anomalies"], res["historique"]

PL = planning.load_planning(P.planning_csv)

with tab_exe:
    st.caption("TL saisis dans CarthagoTrade et absents de l'historique Atlas = TL à exécuter (un TL « Exécuté » dans Trade "
               "sans débit Atlas est classé ⚠️ Anomalie). Pour chacun : doublon, "
               "dossier scanné et validé dans TL-One, domiciliation / ATF / autorisation / plafonds (contrôles OV), "
               f"vigilance, blocage ≥ TL + {ui.fmt_dzd(s.provision_majoration_dzd)} DZD, solde disponible.")
    sy = ch = None
    audits = transfers.latest_audit(P.tr_out)
    if audits:
        from tlone import ui_ov, ui_vigilance
        _a, sy, ch, _p = ui_ov.load(P, s, audits[0])
        vig = ui_vigilance.statut_map(P)
    else:
        vig = {}
        st.warning("Aucun lot OV extrait : tous les TL seront « dossier non scanné ».")
    plan = ex.plan(data.get("trade"), data.get("atlas"), data.get("blocage"), data.get("soldes"), sy, ch,
                   transfers.load_decisions(P.decisions_csv), vig, majoration=s.provision_majoration_dzd,
                   tol=s.tolerance_montant_dzd, planning=PL)
    if plan.empty:
        st.success("Aucun TL en attente d'exécution.")
    else:
        cnt = plan["STATUT"].value_counts()
        c = st.columns(6)
        for i, (k, lab) in enumerate((("A_EXECUTER", "✅ Prêts"), ("A_BLOQUER", "🔒 À bloquer"),
                                      ("COMPLEMENT", "📎 Complément"), ("DOUBLON", "⛔ Doublons"),
                                      ("SOLDE_INSUFFISANT", "💰 Solde insuffisant"), ("ANOMALIE", "⚠️ Anomalies"))):
            c[i].metric(lab, int(cnt.get(k, 0)))
        fil = st.multiselect("Statut", list(ex.LIB_STATUT), format_func=ex.LIB_STATUT.get, key="exe_f")
        pv = plan[plan["STATUT"].isin(fil)] if fil else plan
        st.dataframe(pv.assign(STATUT=pv["STATUT"].map(ex.LIB_STATUT)), hide_index=True, **ui.W, height=380,
                     column_config={k: st.column_config.NumberColumn(format="%.2f") for k in
                                    ("MONTANT_TL", "MONTANT_BLOQUE", "MONTANT_A_BLOQUER", "RESTE_A_BLOQUER",
                                     "SOLDE_DISPO", "SOLDE_APRES_BLOCAGE")})
        deb_bl, deb_txt = ex.debut_blocage(files)
        fb, fe = ex.fichier_blocages(plan, deb_bl), ex.fichier_employeur(plan)
        st.markdown("**Fichiers à transmettre**")
        d1, d2, d3 = st.columns(3)
        stamp = pd.Timestamp.now().strftime("%Y-%m-%dT%H%M%S")
        d1.download_button(f"🔒 Blocages pour l'agence ({len(fb)})", to_excel_bytes({"Blocage": fb[ex.BLOCAGE_COLUMNS]}),
                           file_name=f"Blocage_a_faire-{stamp}.xlsx", disabled=fb.empty, type="primary")
        d2.download_button(f"📨 Information employeur ({len(fe)})", to_excel_bytes({"TL": fe}),
                           file_name=f"TL_situation_employeur-{stamp}.xlsx")
        d3.download_button("⬇ Détail (Excel)", to_excel_bytes({"TL_A_EXECUTER": plan, "BLOCAGES": fb}),
                           file_name=f"TL_a_executer-{stamp}.xlsx")
        st.caption(f"Blocage : début {deb_bl:%d/%m/%Y} ({deb_txt}), durée {ex.BLOCAGE_JOURS} jours, ordinal 001, DZD, "
                   "référence de dénotage MMAAAA[P1|P2] ; "
                   "uniquement si Solde_Dispo − Σ(TL + 5 000) ≥ 0 (le compte ne doit jamais devenir débiteur). "
                   "Les TL prêts (✅) alimenteront les fichiers CarthagoTrade / CarthagoDom / Règlement (formats à fournir).")

with tab_plan:
    if PL.empty:
        st.info("Planning TL non généré (page 2).")
    else:
        st.caption("Toutes les périodes du contrat (CTS), du début à la fin, avec ce qui a réellement été exécuté "
                   "(débit Atlas, ou TL inscrit au registre TL-One) : les périodes échues non transférées sont des "
                   "reliquats à régulariser, quelle que soit leur ancienneté.")
        pt_all = ex.suivi_planning(PL, transfers.load_registre(P.registre_csv), data.get("trade"), data.get("atlas"),
                                   tol=s.tolerance_montant_dzd)
        pt, _ = ui.horizon_planning(pt_all, "pt_h")
        cnt = pt["STATUT_PERIODE"].value_counts()
        c = st.columns(5)
        for i, k in enumerate(("TRANSFERE", "NON_TRANSFERE", "SAISI_EN_ATTENTE", "ANOMALIE_TRADE", "PARTIEL")):
            c[i].metric(ex.ETAT_PERIODE[k], int(cnt.get(k, 0)))
        st.metric("Reliquat total à régulariser (DZD)", ui.fmt_dzd(pt["RELIQUAT"].sum()))
        f1, f2 = st.columns([2, 2])
        fs = f1.multiselect("État", list(ex.ETAT_PERIODE), format_func=ex.ETAT_PERIODE.get, key="pt_f")
        q = f2.text_input("Salarié / identifiant client", key="pt_q")
        v = pt[pt["STATUT_PERIODE"].isin(fs)] if fs else pt
        if q:
            v = v[v[["NOM_TRAVAILLEUR", "SIEGE_RACINE"]].astype(str).apply(lambda r: q.lower() in " ".join(r).lower(), axis=1)]
        cols = [c for c in ["PERIODE_TL", "NOM_TRAVAILLEUR", "SIEGE_RACINE", "NUMERO_DOMICILIATION",
                            "MONTANT_MAX_THEORIQUE", "MONTANT_TRANSFERE", "RELIQUAT", "STATUT_PERIODE", "TL_EXECUTES",
                            "TL_SAISIS", "TL_ANOMALIE", "DATE_EXECUTION_TL"] if c in v.columns]
        st.dataframe(v[cols].assign(STATUT_PERIODE=v["STATUT_PERIODE"].map(ex.ETAT_PERIODE)), hide_index=True,
                     **ui.W, height=420, column_config={k: st.column_config.NumberColumn(format="%.2f") for k in
                                                        ("MONTANT_MAX_THEORIQUE", "MONTANT_TRANSFERE", "RELIQUAT")})
        st.download_button("⬇ Suivi du Planning (Excel)", to_excel_bytes({
            "SUIVI_PLANNING": pt_all, "RELIQUATS": pt_all[pt_all["RELIQUAT"] > 0]}), file_name="suivi_planning_TL_historique.xlsx")
        hp = ex.hors_planning(PL, data.get("trade"))
        if not hp.empty:
            st.warning(f"{len(hp)} TL sur une période absente du Planning du client (avant le CTS, après, ou DOM non planifiée).")
            st.dataframe(hp[["REF_TL", "CLIENT", "NOM", "PERIODE", "OBJET", "STATUT_TRADE"]], hide_index=True, **ui.W)

with tab_reg:
    from tlone import referentiels, regularisation as rg, ui_vigilance


    @st.cache_data(show_spinner="Analyse de l'historique…", max_entries=4)
    def _regul(_P, sig: tuple):
        R = referentiels.load_all(_P)
        ov_idx = rg.index_ov(rg.audits_historiques(_P))
        return rg.analyser(PL, data.get("trade"), data.get("atlas"), transfers.load_registre(_P.registre_csv), ov_idx,
                           R["atf"], R["aut"], R["rh"], transfers.load_decisions(_P.decisions_csv),
                           tol=s.tolerance_montant_dzd, vigilance=ui_vigilance.statut_map(_P))
    if PL.empty:
        st.info("Planning TL non généré (page 2).")
    else:
        st.caption("Chaque période du Planning, du début du contrat à aujourd'hui, croisée avec tout l'historique : TL "
                   "exécutés (Atlas), TL saisis / rejetés (CarthagoTrade), extractions OV passées, décisions, ATF, "
                   "autorisations et base RH de chaque mois. Période non transférée → motif ; période transférée → "
                   "contrôle a posteriori (part, ATF, autorisation).")
        _sig = (_hk, referentiels.signature(P), tuple((str(x), x.stat().st_mtime) for x in rg.audits_historiques(P)),
                ui.mtime(P.decisions_csv), ui.mtime(P.registre_csv), ui.mtime(P.planning_csv),
                ui.mtime(P.tr_root / "vigilance" / "journal_vigilance.jsonl"))
        rgdf = _regul(P, _sig)
        nt = rgdf[rgdf["CODE_MOTIF"] != ""]
        cs = rgdf[rgdf["CONSTATS"] != ""]
        c = st.columns(4)
        c[0].metric("Périodes analysées", len(rgdf))
        c[1].metric("Périodes non transférées / en cours", len(nt))
        c[2].metric("Reliquat (DZD)", ui.fmt_dzd(nt["RELIQUAT"].fillna(0).sum()))
        c[3].metric("Constats sur TL exécutés", len(cs))
        sy_ = rg.synthese(rgdf)
        if not sy_.empty:
            a_, b_ = st.columns([3, 2])
            a_.dataframe(sy_, hide_index=True, **ui.W, column_config={"Reliquat (DZD)": st.column_config.NumberColumn(format="%.2f")})
            b_.bar_chart(sy_.set_index("Motif")["Périodes"], height=260)
        f1, f2 = st.columns(2)
        mot = f1.multiselect("Motif principal", sorted(nt["MOTIF_PRINCIPAL"].unique()), key="rg_m")
        q_ = f2.text_input("Salarié / identifiant client", key="rg_q")
        v_ = nt[nt["MOTIF_PRINCIPAL"].isin(mot)] if mot else nt
        if q_:
            v_ = v_[v_[["NOM_TRAVAILLEUR", "SIEGE_RACINE"]].astype(str).apply(lambda r: q_.lower() in " ".join(r).lower(), axis=1)]
        st.dataframe(v_.drop(columns=["CODE_MOTIF"]), hide_index=True, **ui.W, height=ui.hauteur(len(v_)),
                     column_config={k: st.column_config.NumberColumn(format="%.2f") for k in
                                    ("PART_PERIODE", "EXECUTE_ATLAS", "RELIQUAT", "ATF_MOIS", "AUTORISATION_MOIS")})
        if not cs.empty:
            st.markdown("**Constats a posteriori sur des TL exécutés**")
            st.dataframe(cs[["PERIODE_TL", "NOM_TRAVAILLEUR", "SIEGE_RACINE", "PART_PERIODE", "EXECUTE_ATLAS", "TL_EXECUTES",
                             "ATF_MOIS", "AUTORISATION_MOIS", "CONSTATS"]], hide_index=True, **ui.W, height=ui.hauteur(len(cs)))
        st.download_button("⬇ Régularisation (Excel)", to_excel_bytes({"SYNTHESE": sy_, "NON_TRANSFERE": nt, "CONSTATS": cs,
                                                                     "TOUTES_PERIODES": rgdf}),
                           file_name="regularisation_TL.xlsx")

with tab_an:
    c = st.columns(4)
    c[0].metric("🔴 Critiques", int((an["GRAVITE"] == "CRITIQUE").sum()))
    c[1].metric("🟠 Élevées", int((an["GRAVITE"] == "ELEVEE").sum()))
    c[2].metric("🟡 À vérifier", int((an["GRAVITE"] == "A_VERIFIER").sum()))
    c[3].metric("TL dans l'historique", int(hist["REF_TL"].nunique()) if not hist.empty else 0)
    dbl = an[an["CODE"] == "H01"]
    if not dbl.empty:
        st.error(f"{len(dbl)} référence(s) TL débitée(s) plusieurs fois dans Atlas — montant transféré deux fois.")
    codes = sorted(an["CODE"].unique()) if not an.empty else []
    pick = st.multiselect("Filtrer par contrôle", codes, key="hist_codes",
                          format_func=lambda x: f"{x} — {an.loc[an['CODE'] == x, 'ANOMALIE'].iloc[0]}")
    view = an[an["CODE"].isin(pick)] if pick else an
    st.dataframe(view.assign(GRAVITE=view["GRAVITE"].map(GRAV)), hide_index=True, **ui.W, height=420)

with tab_hist:
    cols = [c for c in ["REF_TL", "CLIENT", "NOM", "PERIODE", "OBJET", "STATUT_TRADE", "MONTANT_TRADE", "MONTANT_ATLAS",
                        "DATE_OPERATION", "DATE_VALEUR", "DATE_VALEUR_TRADE", "REFERENCE_DENOTAGE", "LIBELLE", "NATIONALITE",
                        "PAYS_DESTINATION", "SOURCE"] if c in hist.columns]
    q = st.text_input("Rechercher (référence TL, client, nom)", key="hist_q")
    hv = hist[cols] if not hist.empty else hist
    if q and not hv.empty:
        hv = hv[hv.astype(str).apply(lambda r: q.upper() in " ".join(r).upper(), axis=1)]
    st.dataframe(hv, hide_index=True, **ui.W, height=460)

with tab_per:
    per = h.periodes_par_client(data.get("trade"), data.get("atlas"))
    st.caption("Périodes effectivement transférées (TL débités dans Atlas — seul le débit fait foi) : base de "
               "la régularisation du Planning et du registre.")
    st.dataframe(per, hide_index=True, **ui.W, height=460)

with tab_bs:
    b, so = data.get("blocage"), data.get("soldes")
    st.subheader("Blocages")
    st.dataframe(b if b is not None else pd.DataFrame(), hide_index=True, **ui.W, height=240)
    st.subheader("Soldes des comptes")
    st.dataframe(so if so is not None else pd.DataFrame(), hide_index=True, **ui.W, height=240)

st.download_button("⬇ Exporter l'analyse (Excel)", to_excel_bytes({
    "TL_A_EXECUTER": plan, "ANOMALIES": an, "HISTORIQUE": hist, "PERIODES": h.periodes_par_client(data.get("trade"), data.get("atlas")),
    **({"BLOCAGES": data["blocage"]} if "blocage" in data else {}),
    **({"SOLDES": data["soldes"]} if "soldes" in data else {})}), file_name="historique_TL.xlsx", type="primary")
