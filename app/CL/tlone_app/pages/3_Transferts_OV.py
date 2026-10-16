import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from tlone import planning, transfers, ui  # noqa: E402
from tlone.common import audit, backup, current_user, to_excel_bytes  # noqa: E402

s = ui.setup("Transferts OV")
P = s.paths
st.title("3 · Transferts (OV)")
st.caption("AS-04 / AS-05 / AS-06 — OV, Annexe I, Annexe II, bulletin · plafond REG-05 = min(Annexe II, "
           f"{s.plafond_pct_net:.0%} du net, part DOM de la période, ATF, autorisation) · provision = OV + "
           f"{ui.fmt_dzd(s.provision_majoration_dzd)} DZD")

tab_run, tab_ref, tab_ctl, tab_dec, tab_reg = st.tabs(
    ["① Extraction", "② Référentiels ATF / autorisations", "③ Contrôles", "④ Décision", "⑤ Registre & suivi"])

with tab_run:
    ui.upload_pdfs(P.tr_in, "up_tr")
    ui.job_panel(s, "ov_extract", "Notebook v26 : 1 appel VLM de classification + 1 d'extraction par page, "
                                  "retry ciblé sur champs critiques → audit_transferts_*.xlsx.")

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
    for t in (tab_ctl, tab_dec, tab_reg):
        with t:
            st.info(f"Aucun classeur audit_transferts_*.xlsx dans `{P.tr_out}` : lancez l'extraction.")
    st.stop()


@st.cache_data(show_spinner="Contrôles en cours…")
def _controls(audit_path: str, keys: tuple):
    a = transfers.read_audit_xlsx(Path(audit_path))
    atf = transfers.load_referential(P.atf_xlsx, transfers.ATF_COLUMNS)
    aut = transfers.load_referential(P.autorisations_xlsx, transfers.AUT_COLUMNS)
    reg = transfers.load_registre(P.registre_csv)
    return transfers.run_controls(a, PL, reg, atf, aut, s)


def _mt(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


with tab_ctl:
    src = st.selectbox("Lot d'extraction", audits, format_func=lambda p: f"{p.name} ({ui.mtime(p)})")
    if PL.empty:
        st.warning("Planning TL non généré : tous les dossiers seront NON_CONFORME (T04).")
    SY, CH = _controls(str(src), (_mt(src), _mt(P.planning_csv), _mt(P.atf_xlsx), _mt(P.autorisations_xlsx),
                                  _mt(P.registre_csv)))
    st.session_state["tr_src"] = str(src)
    m = st.columns(4)
    for i, k in enumerate(["CONFORME", "A_REVOIR", "NON_CONFORME"]):
        m[i].metric(k.replace("_", " ").title(), int((SY["STATUT_CONTROLE"] == k).sum()))
    m[3].metric("Montant OV total (DZD)", ui.fmt_dzd(SY["MONTANT_OV"].sum()))
    fs = st.multiselect("Statut", ["CONFORME", "A_REVOIR", "NON_CONFORME"])
    v = SY[SY["STATUT_CONTROLE"].isin(fs)] if fs else SY
    cols = [c for c in ["FICHIER", "STATUT_CONTROLE", "NOM", "PERIODE_TL", "MONTANT_OV", "PLAFOND_RETENU",
                        "PLAFOND_LIMITANT", "MARGE", "PROVISION_ATLAS", "SOLDE_DOM_APRES", "MOTIFS"] if c in v.columns]
    st.dataframe(v[cols], hide_index=True, **ui.W, height=330,
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in
                                ("MONTANT_OV", "PLAFOND_RETENU", "MARGE", "PROVISION_ATLAS", "SOLDE_DOM_APRES")})
    st.download_button("Exporter les contrôles (Excel)", to_excel_bytes({"SYNTHESE": SY, "CONTROLES": CH}),
                       file_name=f"controles_{src.stem}.xlsx")

    st.divider()
    left, right = st.columns([3, 2])
    with left:
        f = st.selectbox("Détail d'un dossier", list(SY["FICHIER"]))
        row = SY.set_index("FICHIER").loc[f]
        st.markdown(f"**{row['STATUT_CONTROLE']}** · {row.get('NOM') or '?'} · période {row.get('PERIODE_TL') or '?'} · "
                    f"OV {ui.fmt_dzd(row.get('MONTANT_OV'))} {row.get('DEVISE') or ''} · plafond retenu "
                    f"{ui.fmt_dzd(row.get('PLAFOND_RETENU'))} ({row.get('PLAFOND_LIMITANT') or '—'})")
        det = CH[CH["FICHIER"] == f].copy()
        icon = {"OK": "✅", "KO": "❌", "NON_CONTROLABLE": "❔"}
        det.insert(0, "", det["RESULTAT"].map(icon).fillna("ℹ️"))
        st.dataframe(det.drop(columns=["FICHIER"]), hide_index=True, **ui.W, height=560)
    with right:
        ui.pdf_viewer(P.tr_in, f, 1, key=f"trpg_{f}")

with tab_dec:
    dec = transfers.load_decisions(P.decisions_csv)
    base = SY[["FICHIER", "AUDIT_SOURCE", "STATUT_CONTROLE", "NOM", "PERIODE_TL", "PERIODE_ID", "MONTANT_OV",
               "PLAFOND_RETENU", "MOTIFS"]].merge(dec[["FICHIER", "DECISION", "COMMENTAIRE"]], on="FICHIER", how="left")
    base[["DECISION", "COMMENTAIRE"]] = base[["DECISION", "COMMENTAIRE"]].fillna("")
    st.caption("VALIDE exige un rattachement au Planning ; valider un NON_CONFORME exige une justification ; "
               "REJETE exige un motif. Les décisions sont historisées (qui / quand).")
    ed = st.data_editor(base, hide_index=True, **ui.W, key="dec_ed",
                        disabled=[c for c in base.columns if c not in ("DECISION", "COMMENTAIRE")],
                        column_config={"DECISION": st.column_config.SelectboxColumn(options=transfers.DECISION_VALUES),
                                       "PERIODE_ID": None, "AUDIT_SOURCE": None,
                                       "MONTANT_OV": st.column_config.NumberColumn(format="%.2f"),
                                       "PLAFOND_RETENU": st.column_config.NumberColumn(format="%.2f")})
    c1, c2 = st.columns(2)
    if c1.button("💾 Enregistrer les décisions", type="primary"):
        errs = transfers.check_decisions(ed)
        if errs:
            st.error("\n".join(errs))
        else:
            n = transfers.save_decisions(P.decisions_csv, ed, current_user())
            audit(P.audit_log, "TL_DECISIONS", current_user(), n=n, lot=st.session_state.get("tr_src"))
            st.success(f"{n} décision(s) enregistrée(s).")
    if c2.button("📒 Inscrire les TL validés au registre"):
        dec = transfers.load_decisions(P.decisions_csv)
        n = transfers.register(P.registre_csv, SY, dec, current_user())
        audit(P.audit_log, "TL_REGISTRE", current_user(), n=n)
        st.cache_data.clear()
        st.success(f"{n} TL inscrit(s) (statut A_EXECUTER). Les contrôles de cumul en tiennent compte.")

with tab_reg:
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
