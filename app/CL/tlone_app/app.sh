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
streamlit run Accueil.py
