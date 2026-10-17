# TL-One — App Domino (DOM → Planning TL → Transferts OV)

Application Streamlit qui enchaîne les trois étapes du transfert libre des salaires,
au-dessus des notebooks déjà validés (qui ne sont **pas modifiés**).

| Module | Ce que fait l'app | Moteur |
|---|---|---|
| **1 · Contrôles DOM** | Dépôt des PDF, lancement Partie 1 (GPU) et Partie 2 (CPU), **liste des dossiers + matrice de validation** (données contrôlées par l'agence × DOM / CTS / CTR / TTR / CarthagoDom, page PDF au clic, source de référence au choix), calendrier des augmentations, sources de référence, export Carthago | `pipeline_part1_v15_A…`, `pipeline_part2_v15_A…` + `tlone/matrice.py` |
| **2 · Planning TL** | Génération de l'échéancier (portage à l'identique du notebook, vérifié par test), vue par domiciliation, rejets, suivi transféré / solde | `tlone/planning.py` (= `Planning_TL_V15A.ipynb`) |
| **3 · Transferts OV** | Lancement extraction v26 (GPU), référentiels ATF / autorisations, **20 contrôles** par dossier, **liste des dossiers (≈1000) + matrice** OV / Annexe I / Annexe II / Bulletin / Planning / ATF / Autorisation, correction recalculant les contrôles, validation en masse après échantillon, registre des TL, suivi des non-transferts | `pipeline_ocr_vlm_v26…` + `tlone/transfers.py`, `tlone/ov_matrice.py` |

## Matrice de validation DOM (Module 1 › ②)

- Lignes : données contrôlées par l'agence (tableau de correspondance métier) — identité (nom, père,
  mère ⚑ vigilance, nationalité, naissance), employeur, compte / agence / n° domiciliation (Carthago),
  n° de contrat (visa inspection), n° de permis (AA-00000000 / WW-AA-000000), dates de début et
  de fin (TTR = borne : CTS ≥ début TTR, CTS ≤ fin TTR), durée, salaires, part (≤ 95 % du net),
  taux et montant total recalculés, signatures, cachet, visa.
- Cellule rouge = anomalie ; « bloquante » (signature absente, clé RIB, Carthago introuvable,
  part > 95 %) : ne se lève pas par confirmation — correction ou rejet.
- Décisions dans `document_pipeline/V15_A/02b_validation_app/journal_validation_dom.jsonl`
  (append-only, jamais écrasé par la Partie 2) ; le Planning les lit (`matrice.planning_rows`).
- Champs « à extraire » : demandés par l'agence, pas encore lus par la Partie 1
  (`DOM_SIGNATURE_TRAVAILLEUR_PRESENTE`, `DOM_LU_APPROUVEE_TRAVAILLEUR_PRESENTE`,
  `CTS_NUMERO_CONTRAT_INSPECTION_TRAVAIL`, `CTS_DATE_VISA_INSPECTION_TRAVAIL`).

L'app tourne sur un **petit tier CPU** ; chaque traitement lourd part en **Domino Job** sur
le tier GPU, uniquement le temps de l'extraction.

## Contrôles transferts (Module 3)

Principe repris de la Partie 2 : une valeur OCR absente/illisible ⇒ **revue**, jamais rejet
automatique. Seul un écart objectivable sur des valeurs lues est **bloquant**. La décision
reste humaine.

| Code | Contrôle | Réf. | Sévérité |
|---|---|---|---|
| T01 | Pièces OV / Annexe I / Annexe II / Bulletin présentes | REG-11/12 | bloquant (Annexe I : revue) |
| T02 | Mentions obligatoires OV lues | CTL-09 | revue |
| T03 | Montant chiffres = lettres (parseur français) | CTL-09 | bloquant |
| T04 | Rattachement au Planning (siège 07310+6 / compte + période P1/P2) | AS-04 | bloquant |
| T05 | Compte local OV = Annexe II = DOM | CTL-17 | revue |
| T06 | Identité (OV, Annexe I/II, bulletin vs CTS) | REG-01 | revue |
| T07 | Période cohérente entre pièces et nom de fichier | CTL-11/12 | revue |
| T08 | Net bulletin = salaire Annexe II | CTL-12 | revue |
| T09–T13 | OV ≤ Annexe II, ≤ 95 % net, ≤ part DOM de la période (− déjà transféré), ≤ ATF, ≤ autorisation | REG-05 / CTL-15 | bloquant |
| T13b | Autorisation non échue (45 j si pas de date limite) | REG-07 | bloquant |
| T14 / T14b | Pas de TL déjà validé sur la période / doublon dans le lot | CTL-19 | bloquant |
| T15 | Cumul prélèvements ≤ montant domicilié actualisé | REG-08 / CTL-19 | bloquant |
| T16 | N° domiciliation Annexe II = DOM | AS-04 | revue |
| T17 | Devise | AS-04 | revue |

Calculés : plafond retenu + plafond limitant, marge, **provision Atlas = OV + 5 000 DZD**, solde DOM.
Les paramètres à confirmer (Q-01, Q-03) se règlent par variable d'environnement (ci-dessous).

## Déploiement Domino

Voir **`domino/PROCEDURE_TLONE.md`** (arborescence, environnement `tlone` révision 6,
variables, vérifications, publication de l'App, premier parcours).
`domino/check_env.py` : environnements, GPU, modèles + contrôle de démarrage.
`MANIFEST.md5` : empreintes de tous les fichiers (`md5sum -c MANIFEST.md5`).

| Variable | Rôle | Défaut |
|---|---|---|
| `TLONE_DATA_ROOT` | racine des données de l'employeur | `/mnt/data` (bloquant si non défini) |
| `TLONE_RUN_MODE` | `domino` (Jobs) ou `local` (sous-processus) | `domino` si `DOMINO_PROJECT_ID` existe |
| `TLONE_GPU_TIER` / `TLONE_CPU_TIER` | ID du hardware tier des jobs | — (bloquant pour les étapes GPU) |
| `TLONE_<ETAPE>_TIER` / `_ENV` / `_PYTHON` | surcharge par étape (`DOM_EXTRACT`, `DOM_POST`, `OV_EXTRACT`) | tier commun / `TLONE_ENV_ID` / env conda de l'étape |
| `TLONE_APP_PYTHON` | interpréteur de l'app | `/opt/conda/envs/tlone-tf4/bin/python` |
| `TLONE_MODEL_DOM` / `TLONE_MODEL_OV` | remplace `MODEL_PATH` du notebook | chemin du notebook |
| `TLONE_PLAFOND_PCT_NET` | plafond % du net | `0.95` |
| `TLONE_PROVISION_MAJORATION` | majoration provision | `5000` |
| `TLONE_AUTORISATION_JOURS` | validité autorisation | `45` |

Deux environnements conda dans l'image : `tlone-tf5` (Partie 1, Qwen3.8-27B-FP8, transformers 5)
et `tlone-tf4` (app, Partie 2, v26 Qwen2.5-VL-7B, transformers 4.57.0). Chaque étape part en
job avec son interpréteur ; l'app transmet au job sa racine de données (`--data-root`).

## Hors Domino (Mac, vast.ai)

```bash
pip install -r requirements.txt
export TLONE_DATA_ROOT=$HOME/tlone_data TLONE_RUN_MODE=local
python -m tests.fixtures $TLONE_DATA_ROOT     # jeu de démonstration synthétique (optionnel)
streamlit run Accueil.py
```
Sur une machine vast.ai, même commande : les étapes GPU tournent en sous-processus local, chacune dans son venv
(`TLONE_DOM_EXTRACT_PYTHON=…/tlone-tf5/bin/python`, `TLONE_OV_EXTRACT_PYTHON=…/tlone-tf4/bin/python`).

## Exécution des notebooks : ce que le runner modifie (en mémoire uniquement)

Le fichier `.ipynb` n'est jamais réécrit ; le notebook exécuté est archivé dans `runs/`.
- `/mnt/data` → `TLONE_DATA_ROOT` (si différent) ; `MAX_PDFS` / `MAX_DOSSIERS` si « Limiter à N » ;
  `MODEL_PATH` si `TLONE_MODEL_*`.
- `glob('*.pdf')` rendu insensible à la casse : les spécimens sont en `.PDF` et étaient ignorés sous Linux.
- Partie 2 : l'autotest V5.3 contient le compte anonymisé `'ACCOUNT_EXAMPLE'`, qui fait échouer
  ses propres `assert` ; il est remplacé par deux RIB synthétiques qui redonnent exactement les
  valeurs attendues (reste 62 / clé 91, clé 94 valide).

## Tests

`python -m pytest tests` (sans GPU, données synthétiques) : planning comparé au **vrai notebook**
Planning_TL exécuté, classeur de validation, matrices DOM et OV (anomalies, bornes TTR, sources de
référence, corrections, bloquants, passage au Planning), 20 contrôles transferts, registre,
contrôle de démarrage, montants en lettres, patchs du runner sur les 3 notebooks réels.

## Hors périmètre / à brancher ensuite
- ATF et autorisations : chargés comme listes Excel (pas encore extraits des PDF collectifs).
- Vigilance (RPA Hit/No Hit), exécution SWIFT / retours Atlas (Q-05) : le registre est à
  `STATUT_EXECUTION = A_EXECUTER`, prêt à recevoir ces retours.
- Apurement : la vue « non transféré » prépare les attestations ; l'accord Apurement (REG-09) reste hors app.
