import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from tlone import planning, transfers, ui, ui_ov, ui_vigilance  # noqa: E402
from tlone.common import audit, current_user, to_excel_bytes  # noqa: E402

s = ui.setup("Transferts OV")
P = s.paths
ui.hero("Ordres de virement (OV)",
        "Déposez les OV du mois avec leurs annexes : l'IA lit chaque pièce et TL-One vérifie automatiquement le montant "
        "maximum autorisé, l'échéancier, la base RH, l'ATF et l'autorisation. Les OV conformes se valident en lot.",
        ["Lecture IA des scans", "Base RH · ATF · autorisations", "Vigilance & HIT"], etape="Étape 3 sur 5",
        expert_subtitle=f"OV, Annexe I, Annexe II et bulletin lus par l'IA ; plafond = min(Annexe II, {s.plafond_pct_net:.0%} "
                        "du net, part DOM de la période, ATF, autorisation) ; contrôle par la base RH ; vigilance ; "
                        f"provision = OV + {ui.fmt_dzd(s.provision_majoration_dzd)} DZD.")
ui.guide([("Déposer et lire", "un OV ou tout le mois"), ("Référentiels du mois", "base RH, ATF et autorisations"),
          ("Vérifier", "seulement les OV en rouge"), ("Valider en lot", "puis vigilance et registre")])

tab_run, tab_ref, tab_ctl, tab_vig, tab_reg, tab_dec = ui.onglets(
    [("① Déposer et lire", False), ("② Référentiels du mois", False), ("③ Vérifier et valider", False),
     ("④ Vigilance", False), ("⑤ Registre et suivi", False), ("Export des contrôles", True)])

with tab_run:
    if ui.expert():
        ui.upload_pdfs(P.tr_in, "up_tr")
        ui.job_panel(s, "ov_extract", f"Notebook {s.notebooks['ov_extract'].stem} : Qwen2.5-VL-7B, pages en batch GPU, "
                                      "JSON par dossier (reprise) → audit_transferts_*.xlsx.")
    else:
        ui.lecture_panel(s, "ov_extract", "Ordres de virement et annexes",
                         "Un PDF par dossier (OV, Annexe I, Annexe II, bulletin). Les documents déjà lus ne sont jamais "
                         "relus : déposez un seul OV ou tout le mois.", P.tr_in, "up_tr_simple")

with tab_ref:
    from tlone import ui_referentiels
    ui_referentiels.render(P, s, planning.load_planning(P.planning_csv))

audits = transfers.latest_audit(P.tr_out)
PL = planning.load_planning(P.planning_csv)
if not audits:
    for t in (tab_ctl, tab_vig, tab_dec, tab_reg):
        if t is None:
            continue
        with t:
            st.info("Aucun OV lu pour l'instant : déposez les documents et lancez la lecture (onglet ①)."
                    + (f" (`{P.tr_out}`)" if ui.expert() else ""))
    st.stop()


with tab_ctl:
    # un nouveau classeur (extraction terminée) devient le lot affiché, même si un ancien était sélectionné
    if st.session_state.get("ov_lot_newest") != str(audits[0]):
        st.session_state["ov_lot_newest"] = str(audits[0])
        st.session_state["ov_lot"] = audits[0]
    src = st.selectbox("Lot d'extraction" if ui.expert() else "Lecture affichée", audits,
                       format_func=lambda p: (f"{p.name} ({ui.mtime(p)})" if ui.expert() else f"OV lus le {ui.mtime(p)}")
                       + (" — le plus récent" if p == audits[0] else ""), key="ov_lot")
    st.session_state["tr_src"] = str(src)
    if PL.empty:
        st.warning("L'échéancier des transferts n'est pas encore généré (étape 2) : aucun OV ne peut être rattaché "
                   "à un mois prévu." + (" (T04)" if ui.expert() else ""))
    ui_ov.render(P, s, src)

A_, SY, CH, _pl = ui_ov.load(P, s, Path(st.session_state.get("tr_src") or audits[0]))

with tab_vig:
    ui_vigilance.render(P, s, A_, SY, PL)

if tab_dec:
    with tab_dec:
        st.caption("Synthèse et détail des contrôles du lot (valeurs corrigées incluses).")
        st.dataframe(SY, hide_index=True, **ui.W, height=360)
        st.download_button("Exporter les contrôles (Excel)", to_excel_bytes({"SYNTHESE": SY, "CONTROLES": CH}),
                           file_name=f"controles_{Path(st.session_state.get('tr_src') or audits[0]).stem}.xlsx")

with tab_reg:
    vig = ui_vigilance.statut_map(P)
    dec_all = transfers.load_decisions(P.decisions_csv)
    val = set(dec_all[dec_all["DECISION"] == "VALIDE"]["FICHIER"]) if not dec_all.empty else set()
    attente = [f for f in val if vig.get(f) not in ("RAS", "HIT_LEVE")]
    if attente:
        st.info(f"{len(attente)} TL validé(s) en attente de vigilance (non inscrits tant que le retour n'est pas RAS "
                "ou le HIT levé) — onglet ④ Vigilance.")
    if st.button("📒 Inscrire au registre les TL validés et passés en vigilance", type="primary"):
        n = transfers.register(P.registre_csv, SY, dec_all, current_user(), vigilance=vig)
        audit(P.audit_log, "TL_REGISTRE", current_user(), n=n)
        st.cache_resource.clear()
        st.success(f"{n} TL inscrit(s) (statut A_EXECUTER). Les contrôles de cumul en tiennent compte.")
    reg = transfers.load_registre(P.registre_csv)
    st.subheader("Registre des TL validés")
    st.dataframe(reg, hide_index=True, **ui.W, height=260)
    if not reg.empty:
        st.download_button("Exporter le registre", to_excel_bytes({"REGISTRE": reg}), file_name="registre_TL.xlsx")
    st.subheader("Suivi de consommation du Planning")
    from tlone import execution as ex
    _hf, _hd, _hr, _he, _hk = ui.historique_data(P, s)
    cons = ex.suivi_planning(PL, reg, _hd.get("trade"), _hd.get("atlas"), tol=s.tolerance_montant_dzd)
    if cons.empty:
        st.info("Planning absent.")
    else:
        nt = cons[cons["RELIQUAT"] > 0]
        c = st.columns(3)
        c[0].metric("Périodes avec reliquat", len(nt))
        c[1].metric("Reliquat à régulariser (DZD)", ui.fmt_dzd(nt["RELIQUAT"].sum()))
        c[2].metric("Périodes partielles", int((cons["STATUT_PERIODE"] == "PARTIEL").sum()))
        st.caption("Base de travail pour les attestations de non-transfert (AS-07) — délivrance soumise à "
                   "l'accord préalable de la cellule Apurement (REG-09).")
        st.dataframe(cons[["PERIODE_TL", "NOM_TRAVAILLEUR", "NUMERO_DOMICILIATION", "MONTANT_MAX_THEORIQUE",
                           "MONTANT_TRANSFERE", "RELIQUAT", "STATUT_PERIODE", "TL_EXECUTES",
                           "TL_SAISIS", "DATE_EXECUTION_TL"]],
                     hide_index=True, **ui.W, height=360)
        st.download_button("Exporter le suivi (Excel)", to_excel_bytes({"SUIVI_PLANNING": cons, "NON_TRANSFERE": nt}),
                           file_name="suivi_planning_TL.xlsx")
