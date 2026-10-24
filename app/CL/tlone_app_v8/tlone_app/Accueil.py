import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from tlone import cockpit, jobs, preflight, ui  # noqa: E402

s = ui.setup("Accueil")
P = s.paths
K = cockpit.indicateurs(P, s)
f = cockpit._fmt

ui.hero("TL-One · Transfert libre des salaires",
        f"{s.employeur_raison_sociale} — l'IA lit les documents, TL-One contrôle et prépare, vos équipes ne traitent "
        "que les exceptions. Du dossier de domiciliation jusqu'aux fichiers du BOCI, en masse ou dossier par dossier.",
        ["IA documentaire (lecture des scans)", f"{K['nb_controles']} contrôles automatiques", "Base RH = référence",
         "Fichiers BOCI générés et vérifiés", "Multi-employeur", "Journal d'audit"])

# ------------------------------------------------------------------ à faire maintenant
st.markdown("### À faire maintenant")
ui.a_faire([
    dict(ic="📄", t="Domiciliations à vérifier", k=K["dom_restant"],
         s=f"cases en rouge à regarder · {K['dom_prets']} prête(s) à valider", warn=True,
         page="pages/1_Controles_DOM.py", lien="Vérifier les DOM"),
    dict(ic="💸", t="OV à vérifier", k=K["ov_a_verifier"],
         s="montant, mois ou pièce à regarder", warn=True, page="pages/3_Transferts_OV.py", lien="Vérifier les OV"),
    dict(ic="✅", t="OV conformes à valider", k=K["ov_conf_a_valider"],
         s="tous les contrôles sont au vert : validation en lot", page="pages/3_Transferts_OV.py", lien="Valider en lot"),
    dict(ic="🛡️", t="Alertes de vigilance", k=K["vig_hit"],
         s="à analyser (les faux positifs déjà vus sont reconnus)", warn=True, page="pages/3_Transferts_OV.py",
         lien="Analyser"),
    dict(ic="📤", t="TL prêts pour le BOCI", k=K["prets"], kk=f"{K['prets']}",
         s=f"{f(K['montant_prets'])} DZD · fichiers générés en un clic", page="pages/5_Fichiers_BOCI.py",
         lien="Générer les fichiers"),
])
if K["reliquats"]:
    st.info(f"🗓️ {K['reliquats']} mois de salaire non transférés à régulariser ({f(K['reliquat_montant'])} DZD) — "
            "chacun avec son motif.")
    st.page_link("pages/4_Historique_TL.py", label="Voir les mois à régulariser", icon="➡️")

# ------------------------------------------------------------------ chiffres clés
st.markdown("### En chiffres")
c = st.columns(6)
c[0].metric("Salariés suivis", K["salaries"])
c[1].metric("Domiciliations planifiées", K["doms"])
c[2].metric("OV lus par l'IA", K["ov"])
c[3].metric("Anomalies détectées", K["anomalies"])
c[4].metric("TL prêts à exécuter", K["prets"])
c[5].metric("Montant prêt (DZD)", f(K["montant_prets"]))

# ------------------------------------------------------------------ parcours
st.markdown("### Le parcours d'un transfert")
st.caption("Étapes en vert : dans TL-One. Étapes grisées : chez un autre acteur (TL-One prépare et reçoit les fichiers).")
for row in cockpit.rangees(cockpit.etapes(K), 4):
    cols = st.columns(4)
    for col, e in zip(cols, row):
        with col:
            st.markdown(cockpit.carte(e), unsafe_allow_html=True)
            if e.get("page"):
                st.page_link(e["page"], label=e.get("lien", "Ouvrir"), icon="➡️")

st.markdown("### Avant / avec TL-One")
a, b = st.columns(2)
a.markdown(cockpit.AVANT, unsafe_allow_html=True)
b.markdown(cockpit.apres(K), unsafe_allow_html=True)

if ui.expert():
    st.markdown("### Employeurs")
    emp = cockpit.employeurs_resume(s)
    if not emp.empty:
        st.dataframe(emp, hide_index=True, **ui.W)
    st.page_link("pages/0_Employeurs.py", label="Créer ou ouvrir un employeur", icon="🏢")

    with st.expander("Administration : contrôle de démarrage, exécutions, règles"):
        rows = preflight.report(s)
        ko = preflight.blocking(rows)
        (st.error if ko else st.success)(f"Contrôle de démarrage : {len(ko)} point(s) bloquant(s)." if ko
                                         else "Contrôle de démarrage : prérequis réunis.")
        st.dataframe(rows, hide_index=True, column_order=["niveau", "étape", "contrôle", "valeur", "action"], **ui.W)
        runs = jobs.list_runs(s, 10)
        if runs:
            st.dataframe(pd.DataFrame([{"": ui.STATUS_ICON.get(r.get("status"), "•"), "run": r["run_id"],
                                        "statut": r.get("status"), "lancé": r.get("launched_at"),
                                        "fin": r.get("finished_at"), "par": r.get("user")} for r in runs]),
                         hide_index=True, **ui.W)
        st.markdown(f"""
- Plafond OV : min(part Annexe II, **{s.plafond_pct_net:.0%}** du net, part DOM de la période, ATF, autorisation).
- Provision / blocage : OV + {ui.fmt_dzd(s.provision_majoration_dzd)} DZD, 90 jours, à J+1 de l'extraction.
- Autorisation : {s.autorisation_validite_jours} jours après validation si aucune date limite.
- Une valeur illisible n'entraîne jamais de rejet automatique : elle part en revue humaine.
""")
