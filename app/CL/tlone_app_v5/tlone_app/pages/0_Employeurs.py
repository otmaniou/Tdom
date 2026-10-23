import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from tlone import employeurs, ui  # noqa: E402
from tlone.common import audit, current_user  # noqa: E402

s = ui.setup("Employeurs")
home = s.home or s.paths.data_root
ui.hero("Employeurs", "Chaque employeur a son propre espace : domiciliations, Planning TL, OV, référentiels du mois, "
        "fichiers BOCI. Création avec la raison sociale et le NIF.")

reg = employeurs.load(home)
a, b = st.columns([3, 2])
with a:
    q = st.text_input("Rechercher (raison sociale, NIF, code)", key="emp_q")
    v = employeurs.search(reg, q)
    st.dataframe(v.rename(columns={"RAISON_SOCIALE": "Raison sociale", "MOTS_CLES": "Mot-clé de contrôle"}),
                 hide_index=True, **ui.W)
    if not v.empty:
        pick = st.selectbox("Ouvrir l'espace de", list(v["CODE"]),
                            format_func=lambda c: v.set_index("CODE").loc[c, "RAISON_SOCIALE"], key="emp_open")
        if st.button("Ouvrir cet employeur", type="primary"):
            ui.choisir_employeur(pick)
            st.switch_page("Accueil.py")
with b, st.container(border=True):
    st.markdown("**Nouvel employeur**")
    with st.form("emp_new", clear_on_submit=True):
        rs = st.text_input("Raison sociale *")
        nif = st.text_input("NIF *", help="Numéro d'identification fiscale (15 ou 20 chiffres)")
        mc = st.text_input("Mot-clé de contrôle", help="Le nom de l'employeur lu sur les pièces doit contenir ce mot "
                                                      "(par défaut : mot distinctif de la raison sociale)")
        ag = st.text_input("Agence (siège)", value="07310")
        ok = st.form_submit_button("Créer l'employeur", type="primary")
    if ok:
        try:
            row = employeurs.create(home, rs, nif, current_user(), mots_cles=mc, agence=ag)
            audit(s.paths.audit_log, "EMPLOYEUR_CREATION", current_user(), code=row["CODE"], raison_sociale=row["RAISON_SOCIALE"])
            msg = employeurs.nif_ok(nif)[1]
            st.success(f"Employeur {row['RAISON_SOCIALE']} créé (code {row['CODE']})." + (f" {msg}" if msg else ""))
            ui.choisir_employeur(row["CODE"])
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

if not reg.empty:
    with st.expander("Compléter un employeur (NIF, mot-clé, agence)"):
        c = st.selectbox("Employeur", list(reg["CODE"]), key="emp_edit",
                         format_func=lambda x: reg.set_index("CODE").loc[x, "RAISON_SOCIALE"])
        r = reg.set_index("CODE").loc[c]
        with st.form("emp_upd"):
            rs2 = st.text_input("Raison sociale", value=r["RAISON_SOCIALE"])
            nif2 = st.text_input("NIF", value=r["NIF"])
            mc2 = st.text_input("Mot-clé de contrôle", value=r["MOTS_CLES"])
            ag2 = st.text_input("Agence", value=r["AGENCE"])
            act = st.selectbox("Actif", ["OUI", "NON"], index=0 if r["ACTIF"] != "NON" else 1)
            if st.form_submit_button("Enregistrer"):
                employeurs.update(home, c, RAISON_SOCIALE=rs2.upper(), NIF="".join(ch for ch in nif2 if ch.isdigit()),
                                  MOTS_CLES=mc2, AGENCE=ag2, ACTIF=act)
                audit(s.paths.audit_log, "EMPLOYEUR_MAJ", current_user(), code=c)
                st.rerun()

st.divider()
with st.container(border=True):
    st.markdown("**Employeur de démonstration**")
    st.caption("Crée (ou recrée) l'employeur « DEMO » avec un jeu de données entièrement fictif et cohérent : "
               "12 salariés, dossiers DOM lus, Planning, base RH / ATF / autorisations du mois, 14 OV lus avec des "
               "anomalies voulues, vigilance avec un HIT à analyser, historique CarthagoTrade / Atlas, blocages et soldes. "
               "Aucun GPU nécessaire. Les données des autres employeurs ne sont pas touchées.")
    if st.button("🎬 Créer / réinitialiser l'employeur de démonstration"):
        from tlone import demo
        with st.spinner("Construction du jeu de démonstration…"):
            root = demo.build(home, current_user())
        audit(s.paths.audit_log, "DEMO_CREATION", current_user(), dossier=str(root))
        st.cache_data.clear()
        st.cache_resource.clear()
        ui.choisir_employeur(demo.CODE)
        st.success("Employeur de démonstration prêt.")
        st.switch_page("Accueil.py")
