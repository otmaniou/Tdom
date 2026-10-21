import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from tlone import ui, ui_boci  # noqa: E402

s = ui.setup("Fichiers BOCI")
P = s.paths
ui.hero("5 · Fichiers BOCI", "TL conformes → fichiers Trade, DOM et Règlement prêts à injecter, cohérents par "
        "construction et contrôlés automatiquement (valeurs fixes, IBAN, SWIFT, RIB, périodes, doublons).",
        ["Trade_final_BOCI", "DOM_BOCI_Final", "Reglement_FINAL_BOCI"])
ctx = ui_boci.contexte(P, s)
for e in ctx["errs"]:
    st.error(e)
t1, t2, t3, t4, t5 = st.tabs(["① Fichiers BOCI (TL prêts)", "② Fichier Trade pour l'agence", "③ Contrôler des fichiers",
                              "④ Paramètres & valeurs fixes", "⑤ Envois archivés"])
with t1:
    ui_boci.render_final(P, s, ctx)
with t2:
    ui_boci.render_agence(P, s, ctx)
with t3:
    ui_boci.render_check(P, s, ctx)
with t4:
    ui_boci.render_params(P, s)
with t5:
    ui_boci.render_envois(P)
