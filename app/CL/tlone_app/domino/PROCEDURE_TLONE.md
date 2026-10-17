# TL-One — Environnement et déploiement Domino (procédure DWS interne)

Adaptation du « Pas à pas déploiement de l'application » au cas TL-One.
Projet **lié à Git** : le code est dans `/mnt/code`.

## 0. Mettre le code dans le dépôt

Dans un workspace du projet : copier `tlone_app/` dans `/mnt/code/tlone_app/`, puis commit + push
(le pre-run script `git_update_dws.sh` le récupère au démarrage des jobs et de l'app).

## Partie 1 — Build de l'environnement `tlone`

Workspace sur tier **GPU** (pour pouvoir tester), environnement de base habituel (DWS-GPU).

### 1. Deux venvs (au lieu d'un)

transformers 5 (Partie 1) et transformers 4 (v26) ne peuvent pas cohabiter dans un même venv.

```bash
dws

# --- venv 1 : app + Partie 2 + v26 transferts (Qwen2.5-VL-7B)
dws-venv-create tlone-tf4
#   (activer le venv comme dans la procédure, puis)
pip install -r /mnt/code/tlone_app/requirements.txt
pip install torch torchvision "transformers>=4.49,<5" accelerate qwen-vl-utils pillow numpy

# --- venv 2 : Partie 1 DOM (Qwen3.8-27B-FP8)
dws-venv-create tlone-tf5
#   (activer le venv)
pip install torch torchvision "transformers>=5.9" accelerate pymupdf pillow pandas psutil \
            opencv-python-headless openpyxl "nbclient>=0.9" "nbformat>=5.9" "ipykernel>=6.0"
# optionnel (fast path DeltaNet) : pip install causal-conv1d flash-linear-attention
```

Noter le chemin Python de chaque venv (venv activé) :
```bash
which python        # ex. /opt/dws/venvs/tlone-tf4/bin/python  -> à reporter en variables
```

### 2. Tester dans le workspace

```bash
cd /mnt/code/tlone_app
<python tlone-tf4> -m pytest -q tests                       # 23 tests, sans GPU
TLONE_APP_PYTHON=<python tlone-tf4> \
TLONE_DOM_EXTRACT_PYTHON=<python tlone-tf5> \
TLONE_OV_EXTRACT_PYTHON=<python tlone-tf4> \
<python tlone-tf4> domino/check_env.py                       # doit finir par « ✅ environnement prêt »
```
Puis un vrai essai GPU de chaque extraction sur 2 dossiers spécimens :
```bash
TLONE_DATA_ROOT=<dataset> <python tlone-tf5> run_step.py dom_extract --max 2
TLONE_DATA_ROOT=<dataset> <python tlone-tf4> run_step.py ov_extract  --max 2
```

### 3. Export → Dockerfile

```bash
dws-venv-export tlone-tf4          # -> /mnt/code/tlone-tf4.yaml
dws-venv-export tlone-tf5          # -> /mnt/code/tlone-tf5.yaml
dws-dockerfile-init
cp /mnt/code/tlone-tf4.yaml /mnt/code/tlone-tf5.yaml /mnt/dockerfile/desired-packages/
dws-dockerfile-create              # -> /mnt/dockerfile/Dockerfile
```
Vérifier que le Dockerfile généré crée bien les **deux** venvs.

### 4. Création dans Domino

Govern → Environments → Create New Environment → nom `tlone`
1. « Start from an existing Environment » → même environnement de base que le workspace.
2. Customize before building.
3. Dockerfile Instructions : contenu de `/mnt/dockerfile/Dockerfile`.
4. Pluggable Workspace Tools : bloc jupyterlab / vscode de la procédure.
5. Pre Run Script : `bash /dws/git/git_update_dws.sh`
6. Build.

## Partie 2 — Données et variables

**Dataset** `tlone_data` (onglet Data du projet). En projet Git il est monté sous
`/mnt/data/tlone_data` — vérifier avec `ls /mnt/data` dans un workspace. Y copier
l'arborescence actuelle de `/mnt/data` (domiciliations_in, parametres_augmentation.xlsx,
Dossier de domiciliation.xlsx, document_pipeline/…).

**Variables d'environnement du projet** (Settings) :
```
TLONE_DATA_ROOT          = /mnt/data/tlone_data
TLONE_APP_PYTHON         = <python tlone-tf4>
TLONE_DOM_POST_PYTHON    = <python tlone-tf4>
TLONE_OV_EXTRACT_PYTHON  = <python tlone-tf4>
TLONE_DOM_EXTRACT_PYTHON = <python tlone-tf5>
TLONE_DOM_EXTRACT_TIER   = <ID tier GPU 80 Go>
TLONE_OV_EXTRACT_TIER    = <ID tier GPU>
TLONE_DOM_POST_TIER      = <ID tier CPU>
```

## Plusieurs versions de l'app

Ne pas utiliser `/mnt/tlone_app` : en projet Git, seuls `/mnt/code` (dépôt) et `/mnt/data`
(datasets) existent dans les conteneurs des jobs et de l'app ; un dossier créé ailleurs dans
`/mnt` disparaît à l'arrêt du workspace.

Une version = un dossier dans le dépôt :
```
/mnt/code/tlone_app_v1/      (production)
/mnt/code/tlone_app_v2/      (essai, ex. PaddleOCR-VL)
```
- Chaque version lance **ses propres** jobs : la commande des jobs suit automatiquement le
  dossier d'où tourne l'app (pas de TLONE_JOB_CMD à changer).
- Une app Domino par version : App file = `tlone_app_v2/app.sh`.
- Données séparées pour un essai : `TLONE_DATA_ROOT` différent (ex. `/mnt/data/tlone_data_v2`),
  sinon v1 et v2 écrivent dans le même classeur de validation et le même registre.
- Les variables d'environnement étant au niveau du projet, une version d'essai à données
  séparées se place de préférence dans un projet Domino distinct (ou via les variables de l'app,
  si ta version de Domino le permet).

## Partie 3 — Publier l'app

Deployments → Apps → Publish Domino App
1. **Details** : nom `TL-One`.
2. **Code** : App file = `tlone_app/app.sh`
   (si le champ n'accepte qu'un fichier racine : copier `domino/app.sh.racine` en `/mnt/code/app.sh`).
3. **Deployment** : Environment = `tlone`, tier **CPU** (l'app ne charge aucun modèle ;
   les extractions partent en jobs sur leur propre tier GPU).
4. **Data** : attacher le dataset `tlone_data`.
5. **Access & sharing** : restreint aux utilisateurs du projet (données clients).
6. Vérification : Pending → Running ; en cas d'erreur, View Execution Details.

Premier test dans l'app : Module 1 › ① Traitement › « DOM — Normalisation » avec
« Limiter à 2 » (CPU, peu coûteux) pour valider le lancement des jobs.
