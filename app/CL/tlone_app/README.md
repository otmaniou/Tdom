# TL-One — App Domino (DOM → Planning TL → Transferts OV)

Application Streamlit qui enchaîne les trois étapes du transfert libre des salaires,
au-dessus des notebooks déjà validés (qui ne sont **pas modifiés**).

| Module | Ce que fait l'app | Moteur |
|---|---|---|
| **1 · Contrôles DOM** | Dépôt des PDF, lancement Partie 1 (GPU) et Partie 2 (CPU), tableau de bord DQ, **validation humaine** ligne par ligne avec aperçu de la page PDF, report des décisions après un nouveau run, calendrier des augmentations, export Carthago | `pipeline_part1_v15_A…`, `pipeline_part2_v15_A…` |
| **2 · Planning TL** | Génération de l'échéancier (portage à l'identique du notebook, vérifié par test), vue par domiciliation, rejets, suivi transféré / solde | `tlone/planning.py` (= `Planning_TL_V15A.ipynb`) |
| **3 · Transferts OV** | Lancement extraction v26 (GPU), référentiels ATF / autorisations, **20 contrôles** par dossier, décision VALIDE/REJETE historisée, registre des TL, suivi des non-transferts | `pipeline_ocr_vlm_v26…` + `tlone/transfers.py` |

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

1. Copier ce dossier à la **racine** du projet Domino (sinon adapter `TLONE_JOB_CMD`).
2. Environnement : celui des notebooks (torch, transformers…) + `pip install -r requirements.txt`.
3. Variables d'environnement du projet :

| Variable | Rôle | Défaut |
|---|---|---|
| `TLONE_DATA_ROOT` | racine des données (comme les notebooks) | `/mnt/data` |
| `TLONE_RUN_MODE` | `domino` (Jobs) ou `local` (sous-processus) | `domino` si `DOMINO_PROJECT_ID` existe |
| `TLONE_GPU_TIER` / `TLONE_CPU_TIER` | **ID** du hardware tier des jobs | tier par défaut du projet |
| `TLONE_JOB_CMD` | commande des jobs | `python run_step.py` |
| `TLONE_MODEL_DOM` / `TLONE_MODEL_OV` | remplace `MODEL_PATH` du notebook (ex. test PaddleOCR-VL) | chemin du notebook |
| `TLONE_PLAFOND_PCT_NET` | plafond % du net (Q-01) | `0.95` |
| `TLONE_PROVISION_MAJORATION` | majoration provision (REG-06) | `5000` |
| `TLONE_AUTORISATION_JOURS` | validité autorisation (REG-07, Q-03) | `45` |

4. **Publish › App** : fichier `app.sh` (port 8888), tier CPU.
5. Les jobs utilisent l'API Domino v4 (`/v4/jobs/start`) via `DOMINO_API_PROXY`, sinon
   `DOMINO_API_HOST` + `DOMINO_USER_API_KEY`. Sur certaines versions de Domino, une App ne
   peut pas lancer de job : dans ce cas lancer `python run_step.py <étape>` en job manuel —
   l'app suit l'exécution via `runs/<run_id>.status.json` de la même façon.

Arborescence (sous `TLONE_DATA_ROOT`) : identique aux notebooks, plus
`referentiels/ATF.xlsx`, `referentiels/AUTORISATIONS.xlsx`,
`document_pipeline/V15_A/04_transferts/` (décisions, registre),
`document_pipeline/runs/` (notebooks exécutés, statuts) et `document_pipeline/audit_tlone.jsonl`.

## Hors Domino (Mac, vast.ai)

```bash
pip install -r requirements.txt
export TLONE_DATA_ROOT=$HOME/tlone_data TLONE_RUN_MODE=local
python -m tests.fixtures $TLONE_DATA_ROOT     # jeu de démonstration synthétique (optionnel)
streamlit run Accueil.py
```
Sur une machine vast.ai, même commande : les étapes GPU tournent en sous-processus local.

## Exécution des notebooks : ce que le runner modifie (en mémoire uniquement)

Le fichier `.ipynb` n'est jamais réécrit ; le notebook exécuté est archivé dans `runs/`.
- `/mnt/data` → `TLONE_DATA_ROOT` (si différent) ; `MAX_PDFS` / `MAX_DOSSIERS` si « Limiter à N » ;
  `MODEL_PATH` si `TLONE_MODEL_*`.
- `glob('*.pdf')` rendu insensible à la casse : les spécimens sont en `.PDF` et étaient ignorés sous Linux.
- Partie 2 : l'autotest V5.3 contient le compte anonymisé `'ACCOUNT_EXAMPLE'`, qui fait échouer
  ses propres `assert` ; il est remplacé par deux RIB synthétiques qui redonnent exactement les
  valeurs attendues (reste 62 / clé 91, clé 94 valide).

## Tests

`python -m pytest tests` (sans GPU) : planning comparé au **vrai notebook** Planning_TL exécuté,
round-trip du classeur de validation, report de décisions, 20 contrôles transferts, registre,
montants en lettres, patchs du runner sur les 3 notebooks réels.

## Hors périmètre / à brancher ensuite
- ATF et autorisations : chargés comme listes Excel (pas encore extraits des PDF collectifs).
- Vigilance (RPA Hit/No Hit), exécution SWIFT / retours Atlas (Q-05) : le registre est à
  `STATUT_EXECUTION = A_EXECUTER`, prêt à recevoir ces retours.
- Apurement : la vue « non transféré » prépare les attestations ; l'accord Apurement (REG-09) reste hors app.
