# TL-One — Procédure Domino (état réel du projet TL_one_domino)

Projet **à fichiers Domino** (pas de Git) : le code vit dans `/mnt/code`, les données dans
le dataset monté sous `/mnt/data/document_pipeline`. On enregistre avec
**File Changes › Sync All Changes** (pas de `git commit`).

## 1. Arborescence

```
/mnt/code/
├── app.sh                 ← lanceur de l'App Domino (copie de domino/app.sh.racine)
└── tlone_app_v1/          ← une version de l'app = un dossier (v2, v3… pour les essais)
    ├── Accueil.py  app.sh  run_step.py  requirements.txt  MANIFEST.md5
    ├── pages/  tlone/  tests/  notebooks/  domino/

/mnt/data/document_pipeline/
├── _commun/ {carthago, salaries, atlas/blocages, atlas/soldes, reglementaire, _modeles}
└── employeurs/TOSYALI/          ← TLONE_DATA_ROOT
    ├── domiciliations_in/  transferts_in/  transferts_out/  referentiels/
    ├── Dossier de domiciliation.xlsx  parametres_augmentation.xlsx
    └── document_pipeline/V15_A/ {01_extraction_raw, 02_postprocessing, 02b_validation_app,
                                  03_planning_tl, 04_transferts}  + runs/
```
Changer de version : modifier la ligne de `/mnt/code/app.sh` (`tlone_app_v1` → `v2`), Stop/Start de l'App.

## 2. Environnement `tlone` (Govern › Environments)

- Base : *Domino DWS Ingenuity GPU Standard 1.1.1*, Dockerfile produit par la chaîne DWS
  (deux environnements conda `tlone-tf4` et `tlone-tf5`).
- **Révision 6** : ajouter les lignes de `domino/Dockerfile_instructions.txt` (paquets de l'app,
  verrou des versions torch/transformers, contrôle final). Les logs du build doivent afficher
  `tf4 OK 4.57.0 …` et `tf5 OK 5.x …`. Puis : révision 6 **Active**.
- Jamais de Dockerfile dans le projet (jeton Artifactory).

## 3. Variables d'environnement du projet (Settings)

| Variable | Valeur |
|---|---|
| `TLONE_DATA_ROOT` | `/mnt/data/document_pipeline/employeurs/TOSYALI` |
| `TLONE_RUN_MODE` | `domino` |
| `TLONE_GPU_TIER` | identifiant du tier H100 (ex. `shared-gpu-12x48-H100-1x80`) |
| `TLONE_ENV_ID` | (facultatif) ID de l'environnement `tlone` si ce n'est pas celui par défaut du projet |

Par défaut chaque étape prend son environnement conda : Partie 1 → `tlone-tf5`,
Partie 2 et v26 → `tlone-tf4` (`TLONE_<ETAPE>_PYTHON` pour forcer un autre interpréteur).

## 4. Vérifier dans un workspace (environnement `tlone`, tier GPU)

```bash
cd /mnt/code/tlone_app_v1
md5sum -c MANIFEST.md5 | grep -v ': OK$'                  # rien ne doit s'afficher
grep -rlI $'\r' --include=*.sh --include=*.py . || echo "fins de ligne OK"
/opt/conda/envs/tlone-tf4/bin/python -m pytest -q tests     # tous les tests « passed »
/opt/conda/envs/tlone-tf4/bin/python domino/check_env.py    # environnements, GPU, modèles, prérequis
```

## 5. Publier l'App (Deployments › App)

1. Code : `code/app.sh` (le lanceur racine).
2. Environment : **tlone**, révision Active (6).
3. Hardware : tier **CPU** (l'App ne charge aucun modèle ; les extractions partent en jobs GPU).
4. Data : dataset `document_pipeline` monté.
5. Access : **Restricted** (données clients).
6. Logs attendus : rapport `[TL-One] Contrôle de démarrage …`, puis `You can now view your Streamlit app`.

## 6. Premier parcours de test

1. **Accueil** : bandeau du contrôle de démarrage — corriger les points BLOQUANTS indiqués.
2. **Contrôles DOM › ① Traitement** : déposer 2 PDF, « Copier », puis Partie 1 avec N = 2
   (cocher la confirmation). Suivre le job dans Jobs ; puis Partie 2.
3. **② Dossiers & validation** : ouvrir un dossier, cliquer les cases rouges, corriger /
   confirmer, valider ou rejeter.
4. **Planning TL** : générer (dossiers validés dans la matrice uniquement).
5. **Transferts OV** : déposer les OV, extraction v26, puis **③ Dossiers & validation**.

Un job lancé par erreur : Jobs › cocher › Stop, puis dans l'app « Marquer abandonné ».

## 7. Démonstrations : worker GPU (modèle chargé une seule fois)

Pas de Domino Job : un **worker** tourne dans un workspace GPU que vous ouvrez vous-même ;
l'App lui confie les extractions. Le modèle est chargé une fois, puis chaque demande ne fait
que le traitement des PDF. Les notebooks ne sont pas modifiés.

1. Variable du projet : `TLONE_RUN_MODE=worker` ; App publiée sur un **tier CPU** (Stop/Start).
2. Workspace sur le tier **H100**, environnement `tlone`, puis dans un terminal :
   ```bash
   /opt/conda/envs/tlone-tf4/bin/python /mnt/code/tlone_app_v2/run_worker.py --steps dom_extract --prewarm
   ```
   - `--steps dom_extract` : Partie 1 seulement (Qwen3.8-27B ≈ 55 Go de mémoire GPU) ;
     `--steps dom_extract,ov_extract` charge aussi Qwen2.5-VL-7B (≈ 70 Go au total : à essayer avant la démo).
   - `--prewarm` : charge les modèles tout de suite (sinon à la première demande).
   - Attendre « prêt (modèle chargé) » : l'App affiche alors « Worker GPU actif » dans la barre latérale.
3. Dans l'App : déposer les PDF, « Lancer » → le worker traite, l'App suit le statut (Rafraîchir).
   La Partie 2 (CPU) est exécutée par le worker également.
4. Fin de démo : **Ctrl+C** dans le terminal (libère le GPU), puis arrêter le workspace.

Le terminal du worker affiche la progression du notebook en direct ; le journal de chaque demande
est aussi dans `document_pipeline/runs/<run_id>.log`.
