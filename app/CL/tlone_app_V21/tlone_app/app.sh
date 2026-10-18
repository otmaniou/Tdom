#!/usr/bin/env bash
# Point d'entrée Domino App (Publish > App > fichier app.sh).
# Domino expose l'app sur le port 8888, adresse 0.0.0.0.
set -e
cd "$(dirname "$0")"
mkdir -p ~/.streamlit
cat > ~/.streamlit/config.toml <<EOF
[server]
headless = true
port = 8888
address = "0.0.0.0"
enableCORS = false
enableXsrfProtection = false
maxUploadSize = 500

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#00915A"
EOF
# Python de l'app : TLONE_APP_PYTHON, sinon l'environnement conda tlone-tf4 de l'image. Rien n'est installé ici.
PY="${TLONE_APP_PYTHON:-/opt/conda/envs/tlone-tf4/bin/python}"
echo "[TL-One] python=$PY | TLONE_DATA_ROOT=${TLONE_DATA_ROOT:-NON DEFINI}"
"$PY" -c "import streamlit" 2>/dev/null || { echo "[TL-One] ERREUR : streamlit absent de l'image. Verifier la revision Active de l'environnement tlone."; exit 1; }
# Contrôle de démarrage (rapport dans les logs de l'App ; l'app affiche le même rapport sur l'Accueil)
"$PY" -m tlone.preflight || echo "[TL-One] Des prérequis sont BLOQUANTS : voir le rapport ci-dessus et l'Accueil."
exec "$PY" -m streamlit run Accueil.py
