import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

from tlone import domvalid, jobs, planning, preflight, transfers, ui  # noqa: E402

s = ui.setup("Accueil")
P = s.paths

st.title("TL-One — Transfert libre des salaires")
st.caption("BNP Paribas El Djazaïr · chaîne DOM → Planning TL → Transferts OV · "
           "les dossiers PDF de ce projet sont des spécimens.")

# ---- Contrôle de démarrage : tous les prérequis, avant toute action ----
_rows = preflight.report(s)
_ko = preflight.blocking(_rows)
_warn = [r for r in _rows if r["niveau"] == preflight.WARN]
with st.container(border=True):
    if _ko:
        st.error(f"Contrôle de démarrage : {len(_ko)} point(s) BLOQUANT(S). Les lancements concernés sont désactivés.")
    elif _warn:
        st.warning(f"Contrôle de démarrage : prêt, {len(_warn)} point(s) d'attention.")
    else:
        st.success("Contrôle de démarrage : tous les prérequis sont réunis.")
    with st.expander("Détail du contrôle de démarrage", expanded=bool(_ko)):
        st.dataframe(_rows, hide_index=True, column_order=["niveau", "étape", "contrôle", "valeur", "action"], **ui.W)
        st.caption("Une étape bloquée seulement par « PDF à traiter » ou « JSON de la Partie 1 » est normale "
                   "tant que les fichiers ne sont pas déposés.")

c1, c2, c3 = st.columns(3)

with c1, st.container(border=True):
    st.subheader("1 · Contrôles DOM")
    if P.validation_xlsx.exists():
        prog = domvalid.progress(domvalid.load_manual(P.validation_xlsx))
        dos = domvalid.load_sheet(P.validation_xlsx, domvalid.DOSSIERS_SHEET)
        st.metric("Dossiers post-traités", len(dos))
        st.metric("Lignes restant à décider", int(prog["RESTANT"].sum()) if not prog.empty else 0)
    else:
        st.info("Pas encore de classeur de validation.")
    r = jobs.last_success(s, "dom_post")
    st.caption(f"Dernière Partie 2 réussie : {r['finished_at'] if r else '—'}")
    st.page_link("pages/1_Controles_DOM.py", label="Ouvrir", icon="📄")

with c2, st.container(border=True):
    st.subheader("2 · Planning TL")
    pl = planning.load_planning(P.planning_csv)
    st.metric("Domiciliations planifiées", pl["DOM_ID"].nunique() if not pl.empty else 0)
    st.metric("Périodes", len(pl))
    st.caption(f"Généré le {ui.mtime(P.planning_csv)}")
    st.page_link("pages/2_Planning_TL.py", label="Ouvrir", icon="🗓️")

with c3, st.container(border=True):
    st.subheader("3 · Transferts OV")
    au = transfers.latest_audit(P.tr_out)
    reg = transfers.load_registre(P.registre_csv)
    st.metric("Lots d'extraction", len(au))
    st.metric("TL inscrits au registre", len(reg))
    st.caption(f"Dernier lot : {au[0].name if au else '—'}")
    st.page_link("pages/3_Transferts_OV.py", label="Ouvrir", icon="💸")

st.divider()
st.subheader("Exécutions récentes")
runs = jobs.list_runs(s, 15)
if runs:
    st.dataframe([{"": ui.STATUS_ICON.get(r.get("status"), "•"), "run": r["run_id"], "statut": r.get("status"),
                   "lancé": r.get("launched_at"), "fin": r.get("finished_at"), "par": r.get("user"),
                   "erreur": (r.get("error") or "")[:120]} for r in runs], hide_index=True, **ui.W)
else:
    st.caption("Aucune exécution.")

with st.expander("Règles en vigueur et points à confirmer"):
    st.markdown(f"""
- **Plafond OV (REG-05)** : min(part Annexe II, **{s.plafond_pct_net:.0%}** du net, part DOM de la période,
  ATF, autorisation) — l'assiette et l'arrondi du 95 % restent à confirmer (**Q-01**).
- **Provision Atlas (REG-06)** : OV + {ui.fmt_dzd(s.provision_majoration_dzd)} DZD.
- **Autorisation (REG-07)** : {s.autorisation_validite_jours} jours après validation si aucune date limite
  n'est fournie — point de départ à confirmer (**Q-03**).
- **Cumul DOM (REG-08)** : plafond = somme des montants théoriques du Planning sur la domiciliation
  (y compris augmentations) — dépend de la réponse à **Q-02**.
- Une valeur OCR absente ou illisible n'entraîne jamais de rejet automatique : elle part en revue.
- Ces paramètres se règlent par variables d'environnement (`TLONE_PLAFOND_PCT_NET`, `TLONE_PROVISION_MAJORATION`,
  `TLONE_AUTORISATION_JOURS`).
""")
