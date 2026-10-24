import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from tlone import ui, ui_boci  # noqa: E402

s = ui.setup("Fichiers BOCI")
P = s.paths
ui.hero("Fichiers pour le BOCI",
        "Les TL prêts deviennent en un clic les trois fichiers attendus par le BOCI (Trade, DOM, Règlement), "
        "cohérents entre eux et vérifiés automatiquement avant l'envoi.",
        ["Trade_final_BOCI", "DOM_BOCI_Final", "Reglement_FINAL_BOCI"], etape="Étape 5 sur 5",
        expert_subtitle="TL conformes → fichiers Trade, DOM et Règlement prêts à injecter, cohérents par construction et "
                        "contrôlés automatiquement (valeurs fixes, IBAN, SWIFT, RIB, périodes, doublons).")
ctx = ui_boci.contexte(P, s)
for e in ctx["errs"]:
    st.error(e)
t1, t2, t3, t4, t5 = ui.onglets([("① Générer les fichiers", False), ("② Fichier pour l'agence", False),
                                 ("③ Vérifier un fichier", False), ("Paramètres & valeurs fixes", True),
                                 ("④ Envois archivés", False)])
with t1:
    ui_boci.render_final(P, s, ctx)
with t2:
    ui_boci.render_agence(P, s, ctx)
with t3:
    ui_boci.render_check(P, s, ctx)
if t4:
    with t4:
        ui_boci.render_params(P, s)
with t5:
    ui_boci.render_envois(P)
