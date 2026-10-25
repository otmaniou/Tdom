# TL-One — Dossier de reprise (21/10/2026 — version V4)

Document de passation entre sessions. À lire en premier dans toute nouvelle session.
Source de vérité du code : `/Users/macbookpro/Desktop/tosyali/projet_tl_one/tlone_app` (Mac) = `/mnt/code/tlone_app_v4` (Domino).
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
| OV (GPU) | `pipeline_ocr_vl27.ipynb` (défaut) ; v29 en test (`TLONE_OV_NOTEBOOK=pipeline_ocr_vl29.ipynb`), v28 / v26 disponibles | tlone-tf4 (transformers **4.57.0**) | Qwen2.5-VL-7B |
| Planning | `Planning_TL_V15A.ipynb` (référence, logique reprise dans `tlone/planning.py`) | — | — |

---

## 2. État technique au 19/10/2026

**Domino**
- Projet à fichiers (DFS) `TL_one_domino`. Code : `/mnt/code/tlone_app_v4` ; lanceur `/mnt/code/app.sh` → `bash /mnt/code/tlone_app_v4/app.sh`.
- **Données** : `TLONE_DATA_ROOT=/domino/datasets/local/TL_one_domino/document_pipeline/employeurs/TOSYALI` (dataset NFS partagé App / workspace / jobs).
  `/mnt/data` est le volume local du workspace : ne PAS y mettre les données (non partagé avec l'App).
- Variables : `TLONE_RUN_MODE=worker`, `TLONE_GPU_TIER=shared-gpu-12x48-H100-1x80`, `TLONE_DATA_ROOT` ci-dessus.
- **Mode worker** (démos) : App sur tier CPU ; dans un workspace H100 :
  `/opt/conda/envs/tlone-tf4/bin/python /mnt/code/tlone_app_v4/run_worker.py --steps dom_extract,ov_extract --prewarm --data-root <dossier employeur>`.
  Modèles chargés une fois (≈ 55 Go + 17 Go). Signal de vie `document_pipeline/_commun/worker/worker_heartbeat.json`, écrit toutes
  les 15 s par un fil de fond (aussi pendant le chargement et les longs lots), écriture atomique ; un worker d'une version
  précédente (signal dans `runs/`) est détecté et signalé.
  Les prérequis de l'App contrôlent l'environnement **du worker** (versions remontées dans le heartbeat).
- **Environnement `tlone`** : révision 6 active, mais **tlone-tf4 contient transformers 5.20.1** (non fixé dans le Dockerfile) → v26/v27 en échec.
  Contournement par workspace : `pip install "transformers==4.57.0"` (perdu au redémarrage).
  Correctif : **révision 8** : la chaîne DWS (dws-venv-create / dws-venv-export / dws-dockerfile-create) reçoit les venvs installés avec `domino/env/requirements-tlone-tf4.txt` et `requirements-tlone-tf5.txt` (verrou complet, 104 / 97
  paquets figés ; transformers **4.57.1** dans tlone-tf4 car 4.57.0 est retiré de PyPI, 5.20.1 dans tlone-tf5 ; ajoute
  rapidfuzz, opencv-python-headless, psutil, xlrd) + `domino/env/lignes_fin_dockerfile.txt` (pip check, noyaux
  Jupyter tf4/tf5, contrôle final). tlone-tf4 vérifié ici (Python 3.11) : pip check OK, imports OK, 94 tests OK.
  Jeton Artifactory à régénérer avant le build (il reste dans l'en-tête DWS, jamais dans le projet).
- Copie des fichiers vers Domino : copier-coller GitHub → Notepad++ (Unix LF, UTF-8) → Domino. Vérification :
  `python3 verifier_copie.py --reparer` (empreintes normalisées `MANIFEST_NORM.txt`, attendu 60/60).
- Copie vers le Mac : `SendUserFile` puis `device_commit_files` (fileUuid, force) ; contrôle `md5sum -c MANIFEST.md5` dans
  `$HOME/mnt/projet_tl_one/tlone_app` (VM du Mac) et `python3 verifier_copie.py`.
- Tests : 97 passent (`python3 -m pytest -q tests`).

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

### F-bis. Historique Atlas × CarthagoTrade — LIVRÉ le 20/10/2026 (`tlone/historique.py`, page « 4 · Historique TL »)
- Fichiers déposés dans `historique_in/` (type reconnu par le nom, le plus récent utilisé) :
  `Historique_mouvement_altas-*.xlsx`, `Transfert libre -*.xls`, `Blocage-*.xlsx`, `comptes_solde-*.xlsx`.
- Référence TL extraite du libellé Atlas : « TL » + 8 ou 9 chiffres (l'export Trade contient des TL à 9 chiffres).
- Trade : Nom2 = nationalité, Nom3 = pays de destination. Période lue dans « Objet du transfert » :
  MMAAAA, MAAAA, AAAAMM, AAAAM, mois en lettres, P1/P2/PART/PARTIE/TRANCHE, « n jours » (→ à préciser).
- Contrôles H01 TL débité 2× dans Atlas (critique) · H02 mouvement sans réf TL · H03 plusieurs réf · H04 réf en double
  dans Trade · H05 débit sans TL Trade · H06 client ≠ · H07 montant ≠ · H08 TL rejeté mais débité (critique) ·
  H09 exécuté sans débit · H10 période illisible · H11 compte ≠ client · H12 même mois transféré 2× (critique) ·
  H13 dénotage sans blocage · H14 période dénotage ≠ objet · H15 colonne « Compte à débiter » décalée dans l'export.
- `.xls` : nécessite `xlrd` dans l'image (ajouté à la révision 7) ; sinon enregistrer en .xlsx.
- À confirmer : longueur des références TL (8 ou 9 chiffres), signe des montants Atlas, statuts Trade comptés comme
  « transférés » (Exécuté ; En cours d'exécution pour les doublons de mois), clé blocage ↔ dénotage.

### F-ter. TL à exécuter — LIVRÉ le 20/10/2026 (`tlone/execution.py`, page 4 onglets ② et ④)
- TL à exécuter = TL de l'export Trade absents de l'historique Atlas (ni débités, ni rejetés).
- Statut par TL, dans cet ordre : DOUBLON (même client + même mois qu'un autre TL en attente ou déjà exécuté,
  sauf P1 ≠ P2) → COMPLEMENT (dossier OV non scanné / non validé, contrôles KO : domiciliation, ATF, autorisation,
  plafonds ; vigilance hors RAS / HIT levé ; montant Trade ≠ montant OV) → A_BLOQUER (blocage absent ou
  insuffisant, montant attendu = TL + 5 000 DZD) → SOLDE_INSUFFISANT (Solde_Dispo − Σ restes à bloquer < 0,
  périodes les plus anciennes servies d'abord) → A_EXECUTER.
- Fichiers : `Blocage_a_faire-*.xlsx` (SIEGE, RACINE, ORDINAL 001, DZD, dénotage MMAAAA[P1|P2], montant = reste à
  bloquer, début = aujourd'hui, fin = +90 jours) ; `TL_situation_employeur-*.xlsx` ; `TL_a_executer-*.xlsx`.
- Onglet ④ Planning × TL : référence TL, état (EXECUTE / SAISI_NON_EXECUTE) et montant sur chaque période du Planning ;
  TL hors planning signalés.
- À fournir : formats CarthagoTrade / CarthagoDom / Règlement pour les TL prêts (plus tard : fichiers finaux).

### F-quater. Décisions du 21/10/2026 — LIVRÉ
- Dénotage du blocage : MMAAAA[P1|P2] (confirmé). Début du blocage = **J+1 de l'extraction** (horodatage du nom du
  fichier comptes_solde, sinon Trade, sinon Atlas) ; fin = début + 90 jours.
- **Seul un débit Atlas fait foi d'exécution.** « Exécuté » dans Trade sans débit Atlas = statut **ANOMALIE** (ni
  exécuté, ni en cours) ; il ne compte pas comme exécuté (doublons, H12, périodes transférées) ; un TL saisi sur la
  même période porte une ALERTE.
- **Planning du début à la fin du CTS** avec l'historique réel : `execution.registre_atlas` rattache chaque TL débité
  à sa période du Planning (même période, sinon le mois s'il n'y a qu'une ligne ce mois-là) ; `suivi_planning` donne
  par période : Transféré / Partiel / TL saisi non exécuté / Anomalie Trade / **Reliquat à régulariser** (échu non
  transféré, quelle que soit l'ancienneté) / À venir, et le montant du reliquat. Utilisé pages 2, 3 (⑤) et 4 (④).
- Les contrôles OV T14 (période déjà transférée) et T15 (cumul DOM) tiennent compte des TL débités dans Atlas, y
  compris antérieurs à TL-One (on peut traiter en 2026 un reliquat d'avril 2025). Un TL du registre TL-One de même
  période et même montant qu'un débit Atlas n'est pas compté deux fois.
- OV « lu mais absent de la liste » : (1) avec « Limiter à N », v27 prenait les N premiers PDF **déjà** extraits
  (sautés) → corrigé : N premiers PDF non encore extraits ; (2) le filtre par défaut « À traiter » masque les
  conformes → compteurs affichés sur chaque filtre ; (3) encadré « PDF déposés absents de ce lot » avec la raison
  (erreur lue dans `transferts_out/pipeline.log`, JSON présent, pas encore extrait).

### F-quinquies. Case 70 de l'OV et compléments — LIVRÉ le 21/10/2026
- Règle unique de lecture d'une période : `tlone/periode.py` (`lire`) — case 70 de l'OV, objet Trade, dénotage,
  mois Annexe II. Formats : « JUIN.2026 PART2 », « Juin 26 », « Sept 25 P2 », « Fev.26 P 1 », « 05-2026 2ème partie »,
  052026P1, 06/2026, AAAAM / MAAAA ; dates jj/mm/aaaa ignorées ; « n jours » sans tranche → à préciser.
  Complément : COMPLEMENT / COMPL / COMP / COM / CPLT / RELIQUAT / RAPPEL.
- Contrôles OV : la période vient du **texte de la case 70** (v28 `reference_paiement`, sinon `periode`) ; si la lecture
  mois/tranche du modèle diffère, le texte de la case est retenu et l'écart est signalé en T07. Synthèse :
  REFERENCE_PAIEMENT, COMPLEMENT, LECTURE_PERIODE.
- **Complément** : sur une période déjà transférée (registre ou débit Atlas), T14 = OK « complément de … », et T11
  vérifie cumul + complément ≤ part de la période ; complément sans TL précédent → T14 KO (à revoir) ; second TL sans
  mention de complément → T14 KO comme avant. TL à exécuter : un complément n'est pas un doublon du TL exécuté, mais
  « Complément » si le cumul dépasse la part du Planning ; H12 devient H12b (à vérifier) quand un complément est mentionné.
- Notebook **v28** `pipeline_ocr_vl28.ipynb` (base v27, non activé par défaut) : le prompt demande de recopier mot pour
  mot toute la case « Référence du paiement et observation du donneur d'ordre » (`reference_paiement`, colonne
  « Reference paiement (case 70) ») et ne demande plus mois / année / tranche / complément au modèle ; JSON dans
  `transferts_out/json_dossiers_v28`. Activation pour test : `TLONE_OV_NOTEBOOK=pipeline_ocr_vl28.ipynb` (App + worker).

### V2 — LIVRÉ le 21/10/2026 : processus cible, multi-employeur, base RH, fichiers BOCI, démo CEO
- **Multi-employeur** (`tlone/employeurs.py`, page « Employeurs ») : registre `<home>/_commun/employeurs.csv`
  (CODE, RAISON_SOCIALE, NIF, MOTS_CLES, AGENCE…) ; création = raison sociale + NIF (15 ou 20 chiffres, unique) ;
  recherche ; sélecteur d'employeur dans la barre latérale (toutes les pages). `<home>` = parent de `employeurs/`
  déduit de TLONE_DATA_ROOT (…/employeurs/TOSYALI → home = …/document_pipeline) ; TOSYALI inscrit automatiquement
  (NIF à compléter). `load_settings(employeur)` ; raison sociale de l'employeur = « Lieu de travail » de la vigilance.
- **Worker** : file et signal de vie communs `<home>/_commun/worker/` ; chaque demande porte le dossier de son
  employeur (`data_root`) ; un seul worker GPU pour tous les employeurs. **Relancer le worker avec le code V2.**
- **Référentiels du mois** (`tlone/referentiels.py`, `tlone/ui_referentiels.py`, page OV onglet ②) : base RH
  (`referentiels/base_rh/`, un fichier par mois), ATF au format BNP (`referentiels/atf/`, rapproché à la base RH par
  le matricule SAP), autorisations (`referentiels/autorisations/`, xlsx / csv / html avec tableau). Le fichier
  « Autorisation_Tosyali_aout_2026.html » reçu est une page Gemini enregistrée sans son contenu : à fournir en Excel.
- **Base RH** (`tlone/rh.py`) : une ligne par salarié et par PART ; client = DROITE(GAUCHE(RIB;15);11) ; contrôles
  RH01 RIB, RH02 IBAN (clé + longueur pays), RH03 SWIFT, RH04 part = 95 % × net × jours/30, RH05 part + payable,
  RH06 permis échu, RH07 compte devise / SWIFT absent, RH08 P1 + P2 = 30 jours, RH09 PART en double.
  Spécimen reçu : SENGUL GUVEN et KUCUK FATIH ne respectent pas la règle des 95 %.
- **Contrôles OV par la base RH** (R01–R07) : présence, montant OV = part RH (au-dessus = bloquant), IBAN, SWIFT,
  devise, bénéficiaire (signale un bénéficiaire ≠ salarié), permis ; colonne « Base RH » dans la matrice OV.
  Planning × base RH (page Planning ④) : DOM absente, PART non domiciliée (nouveau contrat), écart de part, permis.
- **Corrections** : un OV « P2 » n'est plus rattaché à la P1 de l'ancienne DOM (T04 KO) ; T11 n'inclut plus le dossier
  lui-même une fois inscrit au registre ; H13 limité à la période couverte par le fichier des blocages ;
  Planning × TL : « transféré » = débit Atlas (un TL seulement validé = « validé / saisi, non exécuté »).
- **Fichiers BOCI** (`tlone/boci.py`, `tlone/ui_boci.py`, page « Fichiers BOCI ») : Trade (30 col., feuille
  Trade_Consolidé), DOM (30 col., feuille DOM), Règlement (47 col., feuille Reglement_Consolidé), valeurs fixes des
  feuilles « valeur fix » + constantes observées (Statut « En cours d'execution », Étape « 06.Dispatcher BOCI »,
  Account Currency DZD). Une ligne par TL prêt → 3 fichiers cohérents ; sources tracées (OV > RH > Trade > Planning
  / CarthagoDom > paramètres). Formats : référence de dénotage Trade AAAA-MM[Pn] ; objet du transfert et REF_DENO
  MMAAAA[Pn] ; DATE VAL = date valeur − 1 ; compte correspondant pour EUR (09990/600003/020/60) ; banque
  intermédiaire par BIC (HDFC → CHASDEFXXXX, PUNB → DEUTDEFFXXX, CNRB → BARCDEFFXXX) ; noms de banque par BIC.
  Paramètres modifiables : `referentiels/boci_parametres.xlsx`. Envois archivés : `sorties_boci/<horodatage>/`.
  Noms : `Trade_final_BOCI_<AAAAMMJJThhmmss>.xlsx`, `DOM_BOCI_Final-<…>.xlsx`, `Reglement_FINAL_BOCI_<n>TL_<…>.xlsx`.
- **Contrôle de fichiers BOCI** (`boci.verifier`) : B01–B06 structure et valeurs fixes, C01–C22 cohérence par TL
  entre fichiers, F01–F11 formats, P01–P03 Planning. Sur les spécimens reçus : 7 bloquants (2 IBAN de 25 caractères,
  2 IBAN différents Trade / Règlement, 2 périodes incohérentes, 1 correspondant EUR manquant) et 20 à vérifier.
- **Fichier Trade pour l'agence** (page BOCI ②) : pré-saisie depuis les OV validés (format Trade, sans réf. TL).
- **Accueil cockpit** (`tlone/cockpit.py`) : parcours en 11 étapes, indicateurs, avant / après, liste des employeurs.
- **Employeur de démonstration** (`tlone/demo.py`) : jeu fictif cohérent (12 salariés, anomalies voulues, HIT,
  reliquats, double débit, solde insuffisant) ; guide `domino/GUIDE_DEMO_CEO.md`.

- **Décisions du 21/10/2026 (soir)** : « Name CLIENT » du Règlement = nom de la base RH ; date valeur (Trade, DOM,
  Règlement Value Date / DATE VAL / DATE VAL1) laissée **vide** : le BOCI la renseigne ; fichier Trade pour l'agence
  sans référence TL (le TL n'existe pas encore).
- **Mémoire des HIT** (`vigilance.memoire_hits / precedent / reconduire / registre_faux_positifs`) : chaque analyse
  (avéré / non avéré + commentaire + auteur + date) est conservée ; quand la même alerte ressort (même client, même
  rubrique, même valeur ; banque / pays / lieu de travail : tous clients), l'analyse précédente est affichée et
  pré-remplie ; si tous les points sont des « non avérés » connus : bouton « ♻️ Reconduire » (événement DECISION
  `reconduit=true`, fiche annotée). Jamais de levée automatique sans clic. Registre des alertes analysées dans
  l'onglet Suivi (export Excel). Retours : colonne « Déjà analysés (non avérés) ».
- À confirmer : format du fichier Trade pour l'agence ; « Name CLIENT » du Règlement = nom du client Carthago
  (le spécimen a « YASIN KHAN » au lieu de « YASIN KHAN YASIN KHAN ») ; DATE VAL = J−1 calendaire ou ouvré ;
  correspondant / intermédiaire pour les autres pays et devises.

### V4 — LIVRÉ le 21/10/2026 (nuit) : autorisations du portail, régularisation, notebooks, performance
Dossier Domino : `/mnt/code/tlone_app_v4` (copie de v3 + fichiers modifiés). Version affichée : TLONE_APP_V4.0.
- **Autorisations du portail** (`tlone/autorisations.py`) : lecture de la page « Personnel étranger : Transfert des
  salaires des expatriés » (en-tête NIF / RC / raison sociale / total / nombre d'articles / code banque et agence ;
  articles « NOM PRÉNOM (MOIS) », 1.0000 mois, prix unitaire, total). Lecture par tableau, sinon par le texte.
  L'année n'est pas dans la page : nom du fichier ou saisie au dépôt ; la **date de validation** de la demande est
  saisie au dépôt ; les deux sont gardées dans `<fichier>.html.json`. Contrôles : NIF de la demande = NIF de
  l'employeur, Σ articles = total, nombre d'articles, quantité × prix = total, doublons. Compte du salarié retrouvé
  par le nom exact dans la base RH (le portail n'a ni compte ni matricule).
- **Régularisation** (`tlone/regularisation.py`, page 4 onglet ⑤) : tout l'historique est réutilisé — non pour
  ré-exécuter, mais pour expliquer. Chaque période du Planning (début → fin du contrat) : période transférée →
  contrôle a posteriori (A01 > part, A02/A03 ATF, A04/A05 autorisation, A06 débit multiple) ; période non transférée
  → motif (M01 OV jamais scanné, M02 TL rejeté Carthago, M03 OV rejeté, M04 OV non validé, M05/M06 ATF, M07/M08
  autorisation, M09 base RH, M10 « Exécuté » sans débit Atlas, M11 saisi non exécuté, M12 vigilance non levée,
  M99 historique du mois incomplet). Le motif principal est le premier manquant dans l'ordre du processus.
  Entrées : extractions OV passées `audit_transferts_*.xlsx` déposées dans `<data_root>/historique_ov/` (page 4 ①),
  ATF / autorisations / base RH des mois passés dans les référentiels (un fichier par mois), Trade / Atlas.
- **Performance** (12 000 TL) : rapprochement 0,9 s, suivi du Planning 1,9 s, régularisation 3,4 s (cache Streamlit).
- **Notebook OV v29** (`pipeline_ocr_vl29.ipynb`, base v28, non activé par défaut) : montants robustes
  (`23.340.43`, `312:255:00`, `410 542,13`), `nature_paiement_case` et `nombre_jours_absence` gardés, date de
  naissance et résidence de l'Annexe I dans l'Excel, **page de chaque pièce** (colonne « Pages par pièce » → TL-One
  ouvre la bonne page), tokens sans padding, version dans chaque JSON, JSON dans `json_dossiers_v29`.
  Nouveau contrôle **R08** : nombre de jours Annexe II = base RH (ligne « Nombre de jours » de la matrice OV).
- **Partie 1 DOM v16** (4 champs « à extraire ») : non livrée volontairement — la Partie 2 vérifie un schéma figé
  (99 champs + empreinte) ; à faire après la démo avec un test GPU sur corpus.

### Revue complète du 22/10/2026 (V4 corrigée)
- **Sélecteur d'employeur** : changer de page ramenait au 1er employeur (TOSYALI) — Streamlit recrée le widget à
  chaque page. La référence est désormais `session_state["employeur"]` (clé du widget = page + employeur, choix via
  rappel) ; l'employeur est aussi gardé dans l'adresse (`?emp=CODE`) : F5 le conserve. Les boutons (Ouvrir, Créer,
  Démo) passent par `ui.choisir_employeur` (plus d'erreur StreamlitWidgetAlreadyInstantiatedError).
- **Worker en rouge alors que lancé** : (1) le signal de vie n'était écrit qu'entre deux étapes → rouge pendant le
  chargement des modèles et les longs lots ; désormais fil de fond toutes les 15 s + écriture atomique ;
  (2) worker lancé depuis une ancienne version (signal dans `runs/`) → détecté et signalé ; (3) worker lancé sans
  TLONE_DATA_ROOT → `--data-root` (commande exacte affichée dans l'App), sinon détection automatique du dataset.
  Orange = chargement, vert = prêt. Le worker affiche au démarrage version, données, signal de vie, file.
- **Vigilance** : une fiche retournée hors modèle ne fait plus planter la page OV (lecture tolérante, libellés
  absents signalés).
- **Accueil** : reliquat de l'étape 2 = même définition que les pages Planning TL et Historique TL.
- Vérifications : 94 tests (Python 3.13 / Streamlit 1.66 et Python 3.11 / Streamlit 1.40), contrôle croisé des
  appels inter-modules (attributs et signatures : 0 écart), pyflakes, parcours navigateur réel de toutes les
  pages et de tous les onglets (DEMO et TOSYALI : 0 exception), boutons démo / planning / reconduction HIT /
  registre / génération BOCI / régularisation, worker réel lancé et vu par l'App, notebooks patchés (v26–v29,
  Parties 1 et 2) : cellules de configuration et de traitement repérées.

### Décision du 23/10/2026 — Planning = dates de référence de la DOM validée
- Seuls les dossiers **validés dans la matrice DOM** sont planifiés (plus d'option) ; non validés / rejetés → Rejets.
- Bornes = **Date de début / Date de fin de référence** retenues dans la matrice (écrites dans
  CTS_DATE_DEBUT_VALIDITE_PERMIS / _FIN, comme le V15A : identifiants inchangés) ; fin absente → début + durée de
  référence − 1 jour ; début absent → CTS_DATE_DEBUT_CONTRAT. La durée retenue (ligne « Durée du contrat ») est
  désormais transmise au Planning (CTS_DUREE_MOIS).
- Feuille / tableau **CONTROLE_DUREE** : mois planifiés = durée de référence (12, 24…) ; ECART signalé ; DOM sans
  contrat initial validé (seulement une augmentation) signalée.
- Filtre d'affichage (Planning ② / ③, Historique ④) : **Toute la durée / Période actuelle / Intervalle (du … au …)** ;
  reliquats calculés sur le Planning complet. Régénérer le Planning après mise à jour.

### Performance des référentiels (23/10/2026, base RH 9 656 lignes, ATF 15 800 lignes)
- Lecture Excel mise en cache sur disque (`referentiels/<type>/.cache_tlone/`, invalidée si le fichier change) et
  en mémoire (`referentiels.load_all`, `dq_rh`) : première lecture ≈ 10 s, ensuite < 1 s par page.
- Aperçus limités à 500 lignes (mois + recherche) au lieu d'envoyer 15 000 lignes au navigateur à chaque clic.
- Planning × base RH : sur un mois de la base RH (dernier par défaut, choix sur la page Planning), calcul linéaire.
- Liens entre bases : ATF → base RH par **matricule SAP** → RIB → client (siège + racine) ; autorisations du portail
  → base RH par **nom exact** ; à défaut de compte, rapprochement de l'OV par nom (similarité) dans le mois.

### Décision du 23/10/2026 (soir) — ID tiers + période dans toutes les bases ; base RH = référentiel de travail
- **Modèles** (page OV › Référentiels › « Modèle (en-têtes) ») : base RH, ATF et autorisations commencent par
  **ID TIERS** (« 07410 109109 ») et **PERIODE** (« 2026-05 » ; « 2026-05P1 » / « 2026-05P2 » si le mois est réparti).
- Lien entre bases, dans l'ordre : ID tiers → (base RH) matricule SAP → nom exact → (contrôle OV) nom approché.
  Identifiant client pour **toutes les agences** (07310, 07410…) : RIB 20 chiffres → DROITE(GAUCHE(;15);11) ; ID tiers,
  compte BOCI 16 chiffres, nom de fichier → 11 premiers chiffres.
- **Bases passées du mois entier** (pas de P1 / P2) acceptées : RH_MENSUELLE ; RIB facultatif si ID tiers (RH11),
  ID tiers ≠ client du RIB (RH10, bloquant), période illisible (RH12), IBAN / SWIFT absents = à vérifier (RH07).
  OV P1 / P2 face à une RH du mois entier : part attendue = montant du mois × quote-part de la période au Planning
  (R02) ; jours Annexe II non contrôlés (R08). OV du mois entier face à une RH P1 + P2 : parts additionnées.
- **ATF et autorisations du mois entier** : plafond d'une partie = montant du mois − autre partie déjà validée /
  transférée (T12 / T13) ; plusieurs lignes du mois pour un ID tiers = additionnées ; régularisation A03 / A05 sur le
  total du mois ; Planning × base RH compare la RH du mois entier au total P1 + P2.
- **Base RH = référence en cas d'anomalie** : colonne « Base RH » dans la matrice DOM (nom, père, mère, naissance,
  compte, permis, dates du permis, durée, salaire, part) et dans la matrice OV. Retenue d'office pour l'identité
  (nom, père, mère, naissance, compte, permis ; OV : nom, compte, bénéficiaire, IBAN, SWIFT, banque, adresse) si la
  pièce de référence est vide, ou contredite alors qu'une autre pièce confirme la RH. Dates, durée, salaire, part :
  au choix du valideur (source « Base RH »). Montant et période de l'OV : toujours ceux de l'OV (réglementaire).

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
| 5 | ~~OV v28 / v29~~ (livrés, à valider sur corpus) ; DOM v16 (4 champs à extraire) | non-régression utilisateur |
| 6 | ~~Fichiers entrants + régularisation de la base~~ (livrés) ; contrôle post-injection | spécimens |

Chaque lot : tests automatiques, `MANIFEST.md5` + `MANIFEST_NORM.txt` régénérés, copie Mac vérifiée, liste des fichiers à copier sur Domino.

---

## 7. Reprise dans une nouvelle session

1. Lire ce document (projet claude.ai « projet_tl_one » ou `domino/DOSSIER_REPRISE.md`).
2. Récupérer l'app depuis le Mac (dossier `tlone_app`), lancer `python3 -m pytest -q tests` (97 attendus) et `python3 verifier_copie.py`.
3. Annoncer le lot attaqué et ses questions ouvertes avant de coder.

### Décision du 24/10/2026 — Validation en lot (sélection multiple) DOM et OV
- Listes DOM (② Dossiers & validation) et OV (③ Dossiers & validation) : interrupteur **« Sélection multiple »** →
  cases à cocher par ligne + **« Tout sélectionner (filtre courant) »** (OV : toutes pages).
- **Valider la sélection** : seuls les dossiers sans anomalie sont validés (DOM « Prêt à valider », aucune case rouge ;
  OV « CONFORME » et rattaché au Planning). Les autres restent à ouvrir un par un (justification obligatoire pour un
  OV non conforme). Confirmation par case à cocher.
- **Échantillon de contrôle obligatoire** avant toute validation en lot : 5 % des dossiers prêts / conformes, minimum 3,
  tirés au sort, à ouvrir et valider un par un (DOM : tirage par empreinte du nom de fichier, stable ; OV : tirage
  existant par lot). Taux à arbitrer avec le CRO (constantes `matrice.ECHANTILLON_PCT` / `ov_matrice.sample`).
- **Rejeter la sélection** : un motif pour tous (DOM : motif client + commentaire ; OV : motif obligatoire).
- Traçabilité : journal DOM `action=VALIDE|REJETE, mode=LOT, echantillon=…` ; OV décisions « Validation en lot —
  échantillon contrôlé : … » ; audit `DOM_MATRICE_VALIDE_LOT`, `DOM_MATRICE_REJETE_LOT`, `TL_VALIDATION_LOT`, `TL_REJET_LOT`.
- Après une validation dans un dossier : passage au prochain dossier **non décidé** (sinon retour à la liste).
- Reprise du stock (2000+ JSON v15 Partie 1) : Partie 2 → matrice → validation en lot des prêts → Planning.
  Performance de la matrice à 2000 dossiers non encore mesurée : à tester après la démo.

### Décision du 24/10/2026 — Tolérances de la matrice DOM (livré)
Les écarts tolérés restent visibles (ⓘ « Tolérance appliquée » dans la case) mais ne comptent plus comme anomalie :
- **Agence domiciliataire** (DOM ↔ CarthagoDom) : comparaison sans « Agence » ni la raison sociale de la banque
  (« Mostaganem » = « Agence Mostaganem ») ; sinon similarité ≥ 90 % (`TLONE_SEUIL_AGENCE`).
- **Employeur** : conforme si chaque pièce contient un mot-clé de l'employeur TL-One (registre des employeurs, colonne
  MOTS_CLES, ex. « TOSYALI ») ; une pièce sans le mot-clé = anomalie. Sans registre : comparaison entre pièces (ancien).
- **N° de permis du TTR** : facultatif ; absent ou différent → ⓘ, non bloquant.
- **N° de domiciliation absent du CTR** : souhaitable, non bloquant. Domiciliation Carthago unique du client → retenue ;
  plusieurs → à vérifier (saisir le n° dans la case CTR) ; aucune → bloquant.
- **Nom / prénom** : similarité ≥ 90 % (`TLONE_SEUIL_NOM`) **et** identifiant client (siège + racine) identique entre le
  compte du DOM et CarthagoDom → ⓘ ; sinon anomalie comme avant.
- **Signatures, mention « lu et approuvé », cachet, date de signature** : non obligatoires pour le moment
  (`TLONE_DOM_FACULTATIFS`, défaut `sig_trav,lu_approuve,sig_emp,cachet,date_sig`). Visa inspection : inchangé.
- Notebooks Partie 1 / Partie 2 non modifiés : les tolérances sont appliquées par l'App sur leurs sorties.

### 24/10/2026 — Arrêt du worker sans Ctrl+C (livré)
- `run_worker.py --arreter --data-root <dossier employeur>` depuis n'importe quel terminal : dépose
  `_commun/worker/STOP`, attend (180 s max, `--attente`) que le worker s'arrête et le confirme.
- `kill` / `pkill -f run_worker.py` (SIGTERM) = même arrêt propre que Ctrl+C : noyaux des modèles fermés (GPU libéré),
  signal de vie effacé. Protection dès le démarrage du worker (avant le chargement des modèles).
- Le worker affiche au démarrage la commande d'arrêt, et à l'arrêt « arrêté : modèles déchargés, GPU libéré ».

### 24/10/2026 — Carthago « trouvée, type DOM/PREDOM inconnu » (corrigé)
- Point « à vérifier » non bloquant, mais la case CarthagoDom n'offrait aucun bouton : dossier invalidable.
  Bouton **« Confirmer : vérifié dans Carthago »** (tracé CONFIRME) sur une case Carthago à vérifier ; un point
  bloquant Carthago reste non confirmable (corriger le CTR, mettre à jour l'export ou rejeter).
- En-tête / liste : « Trouvé, type à vérifier » au lieu de « Non trouvé » pour ce statut.

### 24/10/2026 (après-midi) — Refonte de l'interface : vue essentielle / vue experte (livré)
- **Vue essentielle (par défaut)** pour les agences, le BOCI et la démo : vocabulaire métier, sans run / worker / notebook
  / JSON / Partie 1-2 / codes de contrôle. **Vue experte** (interrupteur de la barre latérale) = l'App complète d'avant
  (paramètres, classeur Partie 2, contrôles détaillés, administration). Logique, contrôles et journaux inchangés.
- Barre latérale : parcours en 5 étapes (Tableau de bord, 1 Domiciliations, 2 Échéancier, 3 OV, 4 Exécution & suivi,
  5 Fichiers BOCI, Employeurs), voyant « Moteur IA » prêt / en préparation / arrêté.
- **Tableau de bord** : « À faire maintenant » (DOM à vérifier, OV à vérifier, OV conformes à valider en lot, alertes de
  vigilance, TL prêts pour le BOCI), mois à régulariser, chiffres, parcours, avant / avec TL-One.
- **Lecture par l'IA** (DOM et OV) : dépôt d'un PDF ou de centaines, compteurs déposés / déjà lus / à lire, un bouton
  « Faire lire N document(s) par l'IA » ; les documents déjà lus ne sont jamais relus. **Barre de progression en direct**
  (`tlone/avancement.py`, rafraîchie toutes les 3 s) : « L'IA lit vos documents… 2 / 4 · en cours : … · reste … ».
- **DOM : lecture puis contrôles enchaînés** (mode worker) : `jobs.launch(..., ensuite="dom_post")`, le worker lance la
  Partie 2 après une Partie 1 réussie.
- Échéancier : « Mettre à jour l'échéancier », alerte si des DOM ont été validées depuis la dernière mise à jour, dossiers
  non planifiés avec leur raison en clair (`planning.motif_lisible`), colonnes en français.
- OV : contrôles en phrases (`ui.CONTROLE_SIMPLE`), colonnes « Montant max. autorisé », « Limité par ».
- Employeur de démonstration : documents marqués « déjà lus » (aucune lecture GPU proposée sur le jeu fictif).

### 24/10/2026 (soir) — Calendrier des augmentations dans le Planning (livré)
- L'éditeur du calendrier (année → mois d'effet) est aussi dans **2 · Échéancier › ① Mettre à jour** (toutes vues) ;
  il s'ouvre seul quand le fichier manque et signale les années d'augmentation des dossiers sans mois d'effet.
  Même fichier `parametres_augmentation.xlsx` que l'onglet Paramètres (vue experte) du Module 1.

### Décision du 24/10/2026 (soir) — Contrôles des OV (livré)
- **Montants consolidés** : une seule ligne de la matrice OV « Montant OV / montants max. » : OV face à la part
  transférable Annexe II (T09), 95 % du net du bulletin (T10), part RH (R02), part de la période au Planning (T11),
  ATF (T12), autorisation (T13). Le plus petit = montant max. retenu (colonne « Retenu » : OV · max. · limité par).
- **Planning TL** : la part transférable de la période (contrat DOM) ne change plus à l'affichage ; ce qui reste après
  les TL déjà transférés / validés est une donnée à part : **part restante du Planning** (`PLANNING_PART_RESTANTE`,
  ligne dédiée de la matrice ; plafond du contrôle T11). Page Planning : « Part restante du planning ».
- **ATF / autorisation proratisées** : pour une partie de mois (P1 / P2), si le montant ATF ou autorisé est la part
  mensuelle du contrat (± 2 %), le plafond = ce montant × jours de la partie / jours du mois (coefficient du Planning
  TL). Sinon : montant du mois − ce qui est déjà transféré sur l'autre partie (règle précédente).
- **T13c (nouveau, bloquant)** : date limite de l'autorisation > date de domiciliation (export CarthagoDom, colonne
  « Date domiciliation » ; information si la date est absente).
- **OV = bénéficiaire seulement** : l'OV ne porte pas le nom du donneur d'ordre ; il sort du contrôle d'identité
  T06 et de la ligne « Nom du salarié ». Le bénéficiaire reste comparé à la base RH (R06).
- **Devise de transfert** : lue dans le libellé de la case Autre (« Transfert en USD » → USD), comparée à la base RH
  (R05). Le montant de l'OV reste en DZD (T17).
- **IBAN** (R03) comparé sans espaces OV / Annexe II / base RH ; **banque** (R09, nouveau) OV / Annexe II / base RH
  (mots génériques BANK, BANKASI, A.Ş.… ignorés, similarité ≥ 80 %) ; **SWIFT** (R04) OV / base RH.
  Une seule pièce lisible → information, pas « à revoir ».
- **Nombre de jours** : plus comparé (R08 retiré) ; affiché pour information.
- **Notebook OV v30** (`pipeline_ocr_vl30.ipynb`, base v29 non modifiée, non activé par défaut) : `beneficiaire_nom`
  = mots après « Nom/Prénom » (long espace possible, libellé retiré) ; `devise_transfert` = devise seule, colonne
  « Devise de transfert » ; texte brut dans « Nature paiement (autre libellé) » ; JSON dans `json_dossiers_v30`.
  Test : `TLONE_OV_NOTEBOOK=pipeline_ocr_vl30.ipynb` (App + worker).

### 25/10/2026 — Lecture de l'OV (zone 50, SWIFT) et affichage des comptes (livré)
- **Zone 50** : le modèle colle parfois la date au compte (« 21062026 0731010844800130 »). TL-One sépare la date
  (jjmmaaaa en tête) et reconstitue le RIB de l'OV : 0270 + siège + racine + ordinal + clé, lecture retenue si la clé
  Modulo 97 est juste (`common.compte_ov`, appliqué à la lecture du classeur OV, toutes versions). Lecture d'origine
  gardée dans `OV.compte_debiteur_lu` ; date de la demande complétée si absente.
- **Notebook v30** (toujours en test) : `ligne_zone50` = toute la ligne recopiée (colonne « Ligne zone 50 (brute) »),
  structure expliquée au modèle (date, code banque 027 facultatif, siège 5, racine 6, ordinal 3, clé 2, DZD) ; SWIFT
  lu case par case avec sa structure (4 lettres banque + pays = pays de l'IBAN + 2 + 3), sans XXX.
- **R10 (nouveau, à vérifier)** : pays du SWIFT (5e-6e lettres) = pays de l'IBAN et 8 ou 11 caractères (détecte
  YAPIKTRI lu pour YAPITRIS).
- **Affichage** : comptes 027 007310 108448 001 30 ; identifiant client 07310 108448 ; IBAN par groupes de 4 (comptes
  sans IBAN, ex. Inde, aussi par 4 pour la lecture) ; SWIFT de la base RH tel qu'écrit (pas de XXX). Les contrôles
  comparent toujours les valeurs sans espaces.

### Décision du 25/10/2026 — Pièce manquante ou non lue = motif de rejet (livré)
- **T01** est toujours bloquant : OV, Annexe I, Annexe II et bulletin de paie obligatoires. Une pièce absente, ou
  trouvée mais dont aucune donnée n'a été lue (page illisible / mal classée), rend le dossier non conforme
  (« Trouvées mais non lues : Bulletin de paie — motif de rejet »). Démo : 07310-990106 (Annexe I manquante) passe de
  « à revoir » à non conforme.
- **T10** (95 % du net) : calculé uniquement sur le net à payer du bulletin. Le repli sur le salaire de l'Annexe II
  est supprimé (il affichait dans la colonne Bulletin un montant absent du bulletin).

### 25/10/2026 (après-midi) — Base RH à titre d'information, date jj|mm|aa en zone 50 (livré)
- **R02** (montant OV = part de la base RH) passe en **information** : affiché (ⓘ, case non rouge), il ne rend plus le
  dossier « à revoir » ni bloquant. Le montant reste plafonné par T09 à T13 (Annexe II, 95 % du net, Planning, ATF,
  autorisation).
- **Zone 50** : la date collée au compte peut aussi être sur 6 chiffres (jj|mm|aa, ex. 24|05|26) ; le RIB est
  reconstitué de même (clé Modulo 97 juste).
