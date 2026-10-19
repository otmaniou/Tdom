import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from tlone import planning, transfers, ui, ui_ov, ui_vigilance  # noqa: E402
from tlone.common import audit, backup, current_user, to_excel_bytes  # noqa: E402

s = ui.setup("Transferts OV")
P = s.paths
st.title("3 · Transferts (OV)")
st.caption("AS-04 / AS-05 / AS-06 — OV, Annexe I, Annexe II, bulletin · plafond REG-05 = min(Annexe II, "
           f"{s.plafond_pct_net:.0%} du net, part DOM de la période, ATF, autorisation) · provision = OV + "
           f"{ui.fmt_dzd(s.provision_majoration_dzd)} DZD")

tab_run, tab_ref, tab_ctl, tab_vig, tab_reg, tab_dec = st.tabs(
    ["① Extraction", "② Référentiels ATF / autorisations", "③ Dossiers & validation", "④ Vigilance",
     "⑤ Registre & suivi", "Export des contrôles"])

with tab_run:
    ui.upload_pdfs(P.tr_in, "up_tr")
    ui.job_panel(s, "ov_extract", f"Notebook {s.notebooks['ov_extract'].stem} : Qwen2.5-VL-7B, pages en batch GPU, "
                                  "JSON par dossier (reprise) → audit_transferts_*.xlsx.")

with tab_ref:
    st.caption("ATF : liste collective déclarée au fisc · Autorisation : liste ministérielle (montant, période, "
               f"validité {s.autorisation_validite_jours} j après DATE_VALIDATION si DATE_LIMITE vide — REG-07, Q-03). "
               "Rapprochement par COMPTE si renseigné, sinon par nom (similarité ≥ "
               f"{s.seuil_similarite_nom:.0%}). MOIS accepte « 2026-03 », « 03/2026 » ou « MARS 2026 ».")
    for label, path, cols in (("ATF", P.atf_xlsx, transfers.ATF_COLUMNS),
                              ("Autorisations", P.autorisations_xlsx, transfers.AUT_COLUMNS)):
        with st.container(border=True):
            c1, c2 = st.columns([2, 1])
            c1.markdown(f"**{label}** — `{path.name}` · mis à jour {ui.mtime(path)}")
            c2.download_button(f"Modèle {label}", to_excel_bytes({label: transfers.template(cols)}),
                               file_name=f"modele_{path.name}", key=f"tpl_{label}")
            up = st.file_uploader(f"Charger {label}", type=["xlsx"], key=f"up_{label}")
            if up and st.button(f"Enregistrer {label}", key=f"save_{label}"):
                backup(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(up.getbuffer())
                audit(P.audit_log, f"UPLOAD_{label.upper()}", current_user(), fichier=up.name)
                st.success("Enregistré.")
            ref = transfers.load_referential(path, cols)
            if not ref.empty:
                manq = [c for c in transfers.REQUIRED[label] if ref[c].isna().all()]
                if manq:
                    st.warning(f"Colonnes vides ou absentes : {', '.join(manq)}")
                st.dataframe(ref.drop(columns=["_MOIS", "_COMPTE"]), hide_index=True, **ui.W,
                             height=200)

audits = transfers.latest_audit(P.tr_out)
PL = planning.load_planning(P.planning_csv)
if not audits:
    for t in (tab_ctl, tab_vig, tab_dec, tab_reg):
        with t:
            st.info(f"Aucun classeur audit_transferts_*.xlsx dans `{P.tr_out}` : lancez l'extraction.")
    st.stop()


with tab_ctl:
    # un nouveau classeur (extraction terminée) devient le lot affiché, même si un ancien était sélectionné
    if st.session_state.get("ov_lot_newest") != str(audits[0]):
        st.session_state["ov_lot_newest"] = str(audits[0])
        st.session_state["ov_lot"] = audits[0]
    src = st.selectbox("Lot d'extraction", audits, format_func=lambda p: f"{p.name} ({ui.mtime(p)})"
                       + (" — le plus récent" if p == audits[0] else ""), key="ov_lot")
    st.session_state["tr_src"] = str(src)
    if PL.empty:
        st.warning("Planning TL non généré : tous les dossiers seront NON_CONFORME (T04).")
    ui_ov.render(P, s, src)

A_, SY, CH, _pl = ui_ov.load(P, s, Path(st.session_state.get("tr_src") or audits[0]))

with tab_vig:
    ui_vigilance.render(P, s, A_, SY, PL)

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
    cons = transfers.consumption(PL, reg, tol=s.tolerance_montant_dzd)
    if cons.empty:
        st.info("Planning absent.")
    else:
        nt = cons[cons["STATUT_PERIODE"] == "NON_TRANSFERE"]
        c = st.columns(3)
        c[0].metric("Périodes échues non transférées", len(nt))
        c[1].metric("Montant non transféré (DZD)", ui.fmt_dzd(nt["SOLDE_RESTANT"].sum()))
        c[2].metric("Périodes partielles", int((cons["STATUT_PERIODE"] == "PARTIEL").sum()))
        st.caption("Base de travail pour les attestations de non-transfert (AS-07) — délivrance soumise à "
                   "l'accord préalable de la cellule Apurement (REG-09).")
        st.dataframe(cons[["PERIODE_TL", "NOM_TRAVAILLEUR", "NUMERO_DOMICILIATION", "MONTANT_MAX_THEORIQUE",
                           "MONTANT_TRANSFERE", "SOLDE_RESTANT", "STATUT_PERIODE", "DATE_EXECUTION_TL"]],
                     hide_index=True, **ui.W, height=360)
        st.download_button("Exporter le suivi (Excel)", to_excel_bytes({"SUIVI_PLANNING": cons, "NON_TRANSFERE": nt}),
                           file_name="suivi_planning_TL.xlsx")
