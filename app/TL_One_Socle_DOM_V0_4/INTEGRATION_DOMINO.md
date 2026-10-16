# Intégration phase DOM → planning dans Domino

## Ce qui existe déjà (notebooks de référence)

- Extraction GPU : `pipeline_part1_v15_A_fast_standardized_qwen3_8_27b(2).ipynb`, schéma 99 champs, checkpoints individuels et TTR-7.
- Post-traitement CPU : `pipeline_part2_v15_A_normalization_dq_confidence(1).ipynb`, normalisation, DQ, rapprochement de la référence CTR/CarthagoDom et feuille `A_VALIDER_MANUELLEMENT`.
- Planning : `Planning_TL_V15A(1).ipynb` ; périodes et augmentations, à alimenter uniquement par un jeu certifié.

## Adaptateur à construire sans toucher aux notebooks

1. Charger un `processed_json` Partie 2 d'un dossier et son RAW Partie 1. Ne jamais fusionner les valeurs des différentes sources sans conserver leurs identités.
2. Associer chaque champ du catalogue aux informations `raw`, `normalized`, `page`, `document_type`, `needs_review` ; pour chaque champ critique, remonter le document d'origine.
3. Associer la **ligne CarthagoDom unique** issue du rapprochement Partie 2, jamais une suggestion non confirmée ; reporter `snapshot_sha256`, `record_id`, `match_cardinality`, `validation_agence_confirmee`, `reference_dom`, `compte_local`, `montant_total`, `nom_complet`, `employeur_id`.
4. Vérifier le contrat JSON Schema, appeler `validate_dom`, stocker les anomalies et l'empreinte de révision. Bloquer tous les états autres que `CONTROLE_OK` pour la certification.
5. Afficher PDF + champ, permettre des corrections justifiées en créant une nouvelle révision ; relancer tous les contrôles après correction.
6. Après validation nominative et confirmation des permissions, créer un certificat et contrôler `may_generate_planning` pour tout dossier transmis au générateur.
7. Conserver l'identifiant de version DOM et l'empreinte du certificat dans chaque ligne du planning ; ne jamais modifier les périodes antérieures sans versionnement.

## Lots

Créer une campagne par employeur et type de traitement. Stocker les PDF et JSON par empreintes et identifiants techniques. Inventorier les ZIP avant inférence ; permettre de relancer un PDF en échec sans retraiter les autres. Le parsing et la classification des PDF se feront en Job GPU ; le contrôle et le planning en Job CPU ; Streamlit ne pilote que les actions et statuts.

## Validation attendue côté métier

- Règles exactes d'augmentation et date d'effet.
- Calcul du montant total à domicilier pour périodes partielles / prorata.
- Liste définitive des champs qui rendent une domiciliation non certifiable.
- Correspondance identité lorsque formats des noms ou ordre du nom/prénom diffèrent.
- Noms exacts des colonnes CarthagoDom et preuve du statut de validation MOCI.
- Confirmation de la lecture CTR du cachet sur des scans d'agences différentes.

## V0.2 — Adaptateur strict CarthagoDom (source unique des libellés)

1. Modifier **uniquement** `config/carthagodom_columns.json` pour tout changement de nom de colonne source.
2. Lors de l'import Excel, conserver les en-têtes **exactement** ; appeler `check_headers` avant tout rapprochement bancaire. Ne jamais utiliser la fonction de détection d'alias du notebook Partie 2 pour cet import.
3. Pour chaque ligne bancaire sélectionnée et vérifiée, appeler `map_bank_row` ; enregistrer la source, le SHA du snapshot, le numéro de ligne et le SHA du mapping.
4. Aucun état « validé agence » ne doit être inféré tant que les **valeurs exactes** d'un véritable champ de statut (ou une preuve indépendante) ne sont pas configurées.
5. Avant certification, vérifier `column_mapping_sha256`. Un changement de configuration rend les certifications précédentes caduques.

**Attention :** aucune extraction CarthagoDom réelle n'est jointe à cette V0.2. Seuls `Client` et `Nom complet/Raison sociale` sont connus comme libellés attendus dans le notebook de référence. Les autres restent inconnus. Le lecteur XLSX et le module de rapprochement CarthagoDom ne sont pas encore connectés.

## V0.4 — Correction d’import CarthagoDom

La capture fournie était transposée pour lecture. L’export original est un **tableau horizontal**. Le module `src/carthagodom_import.py` lit une domiciliation par ligne en conservant les en-têtes exacts du XLSX. Le module vertical est supprimé. Voir `CONFIGURATION_CARTHAGODOM.md`.

Ne pas mettre en production sans vérifier la ligne d'en-tête, les intitulés exacts et le stockage des identifiants dans le vrai fichier d'origine.
