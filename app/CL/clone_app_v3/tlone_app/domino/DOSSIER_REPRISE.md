# TL-One — Dossier de reprise (19/10/2026)

Document de passation entre sessions. À lire en premier dans toute nouvelle session.
Source de vérité du code : `/Users/macbookpro/Desktop/tosyali/projet_tl_one/tlone_app` (Mac) = `/mnt/code/tlone_app_v2` (Domino).
Tous les PDF du projet sont des spécimens. Données réelles : uniquement sur Domino, dataset restreint.

---

## 1. Périmètre

App Streamlit « TL-One » (BNP Paribas El Djazaïr, Domino) pour le transfert libre des salaires des expatriés :
**DOM** (contrôle des dossiers de domiciliation) → **Planning TL** (échéancier des transferts autorisés) →
**OV** (contrôle des ordres de virement mensuels) → registre / suivi.

Notebooks validés (jamais modifiés sur disque ; l'app les exécute avec des patchs en mémoire) :

| Étape | Notebook | Env conda | Modèle |
|---|---|---|---|
| DOM Partie 1 (GPU) | `pipeline_part1_v15_A_fast_standardized_qwen3_8_27b.ipynb` | tlone-tf5 (transformers 5.x) | Qwen3.8-27B-FP8 |
| DOM Partie 2 (CPU) | `pipeline_part2_v15_A_normalization_dq_confidence.ipynb` | tlone-tf4 | — |
| OV (GPU) | `pipeline_ocr_vl27.ipynb` (défaut) ; v26 via `TLONE_OV_NOTEBOOK` | tlone-tf4 (transformers **4.57.0**) | Qwen2.5-VL-7B |
| Planning | `Planning_TL_V15A.ipynb` (référence, logique reprise dans `tlone/planning.py`) | — | — |

---

## 2. État technique au 19/10/2026

**Domino**
- Projet à fichiers (DFS) `TL_one_domino`. Code : `/mnt/code/tlone_app_v2` ; lanceur `/mnt/code/app.sh` → `bash /mnt/code/tlone_app_v2/app.sh`.
- **Données** : `TLONE_DATA_ROOT=/domino/datasets/local/TL_one_domino/document_pipeline/employeurs/TOSYALI` (dataset NFS partagé App / workspace / jobs).
  `/mnt/data` est le volume local du workspace : ne PAS y mettre les données (non partagé avec l'App).
- Variables : `TLONE_RUN_MODE=worker`, `TLONE_GPU_TIER=shared-gpu-12x48-H100-1x80`, `TLONE_DATA_ROOT` ci-dessus.
- **Mode worker** (démos) : App sur tier CPU ; dans un workspace H100 :
  `/opt/conda/envs/tlone-tf4/bin/python /mnt/code/tlone_app_v2/run_worker.py --steps dom_extract,ov_extract --prewarm`.
  Modèles chargés une fois (≈ 55 Go + 17 Go). Signal de vie `runs/worker_heartbeat.json` (âge par epoch, indépendant du fuseau).
  Les prérequis de l'App contrôlent l'environnement **du worker** (versions remontées dans le heartbeat).
- **Environnement `tlone`** : révision 6 active, mais **tlone-tf4 contient transformers 5.20.1** (non fixé dans le Dockerfile) → v26/v27 en échec.
  Contournement par workspace : `pip install "transformers==4.57.0"` (perdu au redémarrage).
  Correctif : **révision 7** (`domino/Dockerfile_instructions.txt`) — build bloqué : **jeton Artifactory expiré**, à régénérer.
- Copie des fichiers vers Domino : copier-coller GitHub → Notepad++ (Unix LF, UTF-8) → Domino. Vérification :
  `python3 verifier_copie.py --reparer` (empreintes normalisées `MANIFEST_NORM.txt`, attendu 38/38).
- Copie vers le Mac : `SendUserFile` puis `device_commit_files` (fileUuid, force) ; contrôle `md5sum -c MANIFEST.md5` dans
  `$HOME/mnt/projet_tl_one/tlone_app` (VM du Mac) et `python3 verifier_copie.py`.
- Tests : 51 passent (`python3 -m pytest -q tests`).

**Contraintes permanentes**
- Jamais de Dockerfile dans le projet ni en photo (jeton Artifactory).
- Pas d'installation au démarrage (tout dans l'image) ; les `%pip install` des notebooks sont neutralisés en mémoire.
- App en accès Restricted. Données confidentielles en dataset restreint. Pas de zip vers Domino.
- Notebooks validés inchangés ; toute évolution = nouvelle version (v16, v28) + non-régression sur corpus par l'utilisateur.

---

## 3. Règles métier déjà en place

**DOM — matrice données × pièces (DOM, CTS, CTR, TTR, Carthago)**
- TTR = borne : début CTS ≥ début TTR, fin CTS ≤ fin TTR, durée ≤ TTR.
- Part transférable ≤ 95 % du net (`TLONE_PLAFOND_PCT_NET`) ; taux = part / salaire ; montant = part × durée (`CTS_DUREE_MOIS`, une seule durée CTS).
- Permis : formats `AA-00000000` / `WW-AA-000000`. Client = `DROITE(GAUCHE(compte;15);11)` ; clé RIB Modulo 97.
- 4 champs « à extraire » (absents des notebooks) : CTS n° inspection travail, CTS date visa inspection, DOM signature travailleur, DOM « lu et approuvé ».
- Niveaux : bloquant / écart / à vérifier. Une confirmation ne lève pas un bloquant ; une correction est re-contrôlée.
- N° domiciliation : si la Partie 2 a vu le CTR vide (« illisible »), l'App recompare le CTR courant (lu ou corrigé) aux domiciliations Carthago du client.
- Journal append-only `02b_validation_app/journal_validation_dom.jsonl` ; décisions → Planning.

**OV — contrôles T01–T17** (`tlone/transfers.py`)
- Retirés le 19/10/2026 : **T16** n° de domiciliation (non contrôlé, affiché pour information) ;
  **T08** net bulletin = salaire Annexe II (Annexe II hors primes ≠ net bulletin : affichés sans comparaison).
- Plafond retenu = min(Annexe II, 95 % net bulletin, part DOM de la période − déjà transféré, ATF, autorisation) ; provision = OV + 5 000 DZD.
- Lecture du classeur v26 et v27 (libellés v27 ramenés aux clés v26) ; période v27 : mois / année / tranche séparés, année sur 2 chiffres admise.
- v27 : reprise sur `transferts_out/json_dossiers` (un PDF déjà en JSON est sauté) ; `INPUT_DIR` redirigé vers `transferts_in`.

---

## 4. Décisions du 19/10/2026 (à implémenter)

### A. Multi-employeur
- **Création** d'un employeur : 2 champs obligatoires **Raison sociale** et **NIF**. L'app crée l'arborescence `employeurs/<CODE>/` (code dérivé de la raison sociale, unique) et l'inscrit dans un référentiel `_commun/employeurs.csv` (CODE, RAISON_SOCIALE, NIF, MOTS_CLES, DATE_CREATION, CREE_PAR, ACTIF).
- **Liste / recherche** des employeurs (raison sociale, NIF) → entrer dans l'**espace employeur** : DOM, Planning TL, OV, registre, fichiers de sortie.
- `TLONE_DATA_ROOT` devient la racine commune ; l'employeur courant est choisi dans l'app (plus de chemin TOSYALI en dur).
- **Contrôle employeur entre pièces** : conforme si le nom lu **contient** le mot-clé de l'employeur
  (« TOSYALI IRON STEEL INDUST », « SPA TOSYALI » → conformes pour TOSYALI). Mots-clés par défaut = mot distinctif de la raison sociale, modifiables.

### B. Tolérances DOM
- **Agence** : Carthago écrit « Agence Mostaganem », les pièces « Mostaganem » → comparer sans le préfixe « Agence ».
- **Pays / nationalité** : table d'équivalence (TURQUE = TURC = TURQUIE ; ALGÉRIENNE = ALGÉRIE ; …), extensible.
- **CTR sans n° de domiciliation** : cas normal (certains CTR n'en ont pas) → pas d'anomalie ; rapprochement Carthago par client + nom.

### C. Planning TL
- Début **et** fin du planning = dates du **CTS** (vérifier l'implémentation actuelle de `tlone/planning.py` et aligner).

### D. Notebooks (accord pour nouvelles versions)
- DOM Partie 1 **v16** : ajouter CTS n° inspection travail, CTS date visa inspection, DOM signature travailleur présente, DOM « lu et approuvé » présent, TTR durée.
- OV **v28** (base v27) : n° de page par pièce, `nature_paiement_case` et `nombre_jours_absence` (actuellement écartés par les whitelists), `date_naissance` / résidence Annexe I dans l'export, fins de prompt tronquées (IMG_8489) à compléter, montant `23.340.43` non normalisé.
- Versions actuelles conservées comme référence ; bascule après non-régression.

### E. Après validation des OV (par dossier ou par liste)
1. **Fichiers vigilance** (modèle Excel fourni par l'utilisateur) : pour chaque dossier ; pour un même client, **un seul fichier si les informations du bénéficiaire sont identiques**, sinon **un fichier par bénéficiaire distinct**.
2. **Retour vigilance** : l'app lit les retours ; **hit** → le TL est bloqué et exige une validation avec motif.
3. **Fichier de blocages pour l'agence** : SIEGE, RACINE, ORDINAL, CLE, DEVISE, MONTANT, REFERENCE_BLOCAGE, DATE_DEBUT, DATE_FIN (par défaut DATE_FIN = DATE_DEBUT + 90 jours).
4. **Fichiers de chargement prod** : CarthagoTrade, CarthagoDom, Règlement (formats à fournir).
5. **Contrôle post-injection** : comparaison fichier généré et transmis à la prod ↔ extraction après la prod (trade, dom, blocage) → rapport d'écarts.

### E-bis. Vigilance — LIVRÉ le 19/10/2026 (`tlone/vigilance.py`, `tlone/ui_vigilance.py`, onglet ④ Vigilance)
- Modèle BNP « CHECK LIST TRANSFERT LIBRE » chargé dans l'app (onglet Modèle → `referentiels/modele_avant_vigilance.xlsx`) ;
  cases repérées par **libellé** en colonne A (le notebook « TOSYALI_Vigilance_complet » utilisait des adresses décalées
  de 2 lignes par rapport au vrai modèle : C3/C4/C10/C11/C14/C29 au lieu de C5/C6/C12/C13/C16/C31).
- Remplissage : Client = nom CTS ; Réf dossier = identifiant client « SSSSS RRRRRR » ; Circuit TL ; Type Création ;
  Banque / pays de la banque (Annexe II, sinon pays du SWIFT) ; Bénéficiaire (vide s'il est le client, ordre indifférent) ;
  Lieu de travail = raison sociale employeur (`TLONE_EMPLOYEUR_RAISON_SOCIALE`) ; Divers individus = père, mère
  (matrice DOM) + signataire Annexe I (v27), un par ligne (`TLONE_VIGILANCE_INDIVIDUS=entier|diese`).
- Regroupement : un fichier par client + bénéficiaire (nom + IBAN + SWIFT).
- Retours (xlsx multiples ou ZIP, lus en mémoire) : RAS / HIT / KO plateforme indisponible / rubrique non renseignée /
  vide / inconnu ; contrôles de structure (client, individus, décalage des rangs, doublon). Fiche retournée conservée
  (`vigilance/retours/fichiers/`). **Analyse des HIT dans TL-One** : fiche affichée, chaque point HIT / à vérifier
  reçoit « avéré » ou « non avéré » + commentaire obligatoire ; tous non avérés → TL libéré (HIT_LEVE), un avéré →
  alerte confirmée et TL rejeté. Analyse écrite dans la colonne COMMENTAIRES → fiche annotée (`vigilance/analyses/`)
  à archiver. Registre : seuls les TL RAS ou HIT levé (`STATUT_VIGILANCE`).
- Granularité retenue : une vigilance par client + bénéficiaire et par lot (pas de réutilisation d'un lot à l'autre).
  En attente : archivage CarthagoTrade (une pièce par TL ?, nommage), durée de validité éventuelle d'un RAS.
- Journal `04_transferts/vigilance/journal_vigilance.jsonl` ; envois `vigilance/envois/VIG_*` ; résultats `vigilance/retours/`.
- À confirmer : format des individus (nom complet ou prénom#nom), format de la réf dossier, nom exact des fichiers retour.

### F. Fichiers entrants (plus tard, formats à convenir sur spécimens)
TL exécutés, TL en cours, opérations exécutées (Atlas via SWIFT), blocages disponibles, soldes disponibles et provisoires.

### G. Régularisation de la base
Charger l'historique des TL exécutés → rattacher chaque TL à sa DOM / période du planning → détecter mois en double,
transferts hors période, cumul > plafond DOM, mois non transférés, TL sans DOM → rapport de régularisation → initialisation du registre.

### H. Interface
Facile et belle : thème BNP, accueil = liste des employeurs ; espace employeur avec indicateurs (dossiers à valider, TL à exécuter,
alertes vigilance / blocage), parcours guidé par étapes, vocabulaire métier, moins de détails techniques (réservés à un onglet « Administration »).

---

## 5. Questions ouvertes

1. **Mots-clés employeur** : dérivés automatiquement de la raison sociale (modifiables) — à confirmer.
2. **CTR sans n° DOM et plusieurs domiciliations Carthago du même client** : la plus récente, ou choix par le valideur ?
3. **Vigilance** : fournir le modèle Excel ; quelles informations bénéficiaire définissent « le même bénéficiaire » (nom + IBAN + SWIFT ?) ; format du retour et valeur qui signifie « hit ».
4. **Blocages** : MONTANT = montant OV ou provision (OV + 5 000) ? DATE_DEBUT = date de validation du TL ? format de REFERENCE_BLOCAGE ? un blocage par TL ou par période ?
5. **CarthagoTrade / CarthagoDom / Règlement** : spécimens (en-têtes réels + 2–3 lignes fictives), format, système cible.
6. **Contrôle post-injection** : spécimens des extractions prod correspondantes et clé de rapprochement.
7. **Fichiers entrants (F)** et **régularisation (G)** : spécimens et profondeur d'historique — plus tard.

---

## 6. Plan par lots (ordre recommandé)

| Lot | Contenu | Dépend de |
|---|---|---|
| 0 | Environnement révision 7 (nouveau jeton) | utilisateur |
| 1 | Multi-employeur (création RS + NIF, liste, espace employeur, données par employeur) + refonte visuelle de la navigation | — |
| 2 | Tolérances DOM (employeur mot-clé, agence, pays/nationalité, CTR sans n° DOM) + planning sur dates CTS | Lot 1 |
| 3 | ~~Vigilance~~ (livré) ; fichier de blocages agence | Q4 |
| 4 | Fichiers prod CarthagoTrade / CarthagoDom / Règlement + contrôle post-injection | Q5, Q6 |
| 5 | Notebooks DOM v16 / OV v28 (nouveaux champs) + branchement dans l'app | non-régression utilisateur |
| 6 | Fichiers entrants (TL exécutés, en cours, Atlas/SWIFT, blocages, soldes) + régularisation de la base | spécimens |

Chaque lot : tests automatiques, `MANIFEST.md5` + `MANIFEST_NORM.txt` régénérés, copie Mac vérifiée, liste des fichiers à copier sur Domino.

---

## 7. Reprise dans une nouvelle session

1. Lire ce document (projet claude.ai « projet_tl_one » ou `domino/DOSSIER_REPRISE.md`).
2. Récupérer l'app depuis le Mac (dossier `tlone_app`), lancer `python3 -m pytest -q tests` (51 attendus) et `python3 verifier_copie.py`.
3. Annoncer le lot attaqué et ses questions ouvertes avant de coder.
