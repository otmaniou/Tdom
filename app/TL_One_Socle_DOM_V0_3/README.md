# TL-One — Socle de certification DOM V0.1 (prototype)

**Périmètre :** plateforme interne BNP Paribas El Djazair, multi-employeurs, phase **dossiers de domiciliations déjà validés en agence**. Cette livraison n'est ni une solution de production, ni une intégration Domino App, ni une validation réglementaire automatique.

## Référence du besoin

L'employeur transmet les pièces via le circuit actuel. La banque récupère les PDF scannés **après domiciliation MOCI**, y compris le **cachet de domiciliation sur le CTR**, et une extraction CarthagoDom indépendante. Les données validées doivent alimenter **DOMICILIATIONS → DOM_VERSIONS → PLANNING_TL**. L'écran Prédomiciliation reste désactivé dans la future App.

## Contenu

| Chemin | Utilité |
|---|---|
| `schemas/catalogue_champs_v15a.json` | Catalogue **exact de 99 champs** issu de `pipeline_part2_v15_A_normalization_dq_confidence(1).ipynb` ; hash d'origine conservé |
| `schemas/contrat_dossier_dom_v0_1.schema.json` | **Contrat canonique** entre notebooks OCR, ligne CarthagoDom rapprochée et moteur de contrôle |
| `config/regles_dom_v0_1.json` | Paramètres initiaux et barrières de certification |
| `src/dom_certification.py` | Validateur déterministe Python : blocages, revue, révision, certification nominative (démonstration) |
| `tests/test_dom_certification.py` | Tests synthétiques de non-régression (aucune donnée client) |
| `examples/dossier_fictif.json` | Un dossier inventé, uniquement pour tester l'interface |
| `INTEGRATION_DOMINO.md` | Étapes d'intégration et limites restant à lever |

## Installation et essais

Aucune dépendance externe n'est nécessaire pour le validateur de démonstration (Python 3.10+).

```bash
cd TL_One_Socle_DOM_V0_1
python -m unittest discover -s tests -v
python src/dom_certification.py examples/dossier_fictif.json
```

## Barrières prévues

- Source documentaire distincte de CarthagoDom : **interdit de combler une lecture CTR impossible avec une donnée CarthagoDom**.
- Référence du cachet `CTR_REFERENCE_DOMICILIATION` comparée à la référence bancaire, après normalisation traçable.
- Un seul rapprochement CarthagoDom acceptable par contrat ; un match multiple ou absent est bloquant.
- Concordance du compte, des dates et des parts transférables ; pas de montants imaginés ; calcul avec `Decimal`.
- Séparation par identifiant employeur et campagne, preuve documentaire par page.
- Alertes bloquantes / à revoir distinctes du statut de certification.
- **Jamais d'autorisation automatique de planning**, même si tous les contrôles sont satisfaits : certification humaine requise.
- Modifications des données ou des règles = invalidation du certificat lié à la révision précédente.

## Restrictions majeures

1. L'adaptateur des JSON réels **Partie 1 / Partie 2 V15-A** vers le contrat canonique reste à écrire et tester sur un dossier réel, en respectant les 99 champs et les 7 champs TTR effectivement extraits. Les notebooks source ne sont **pas modifiés**.
2. L'import ZIP et l'extraction Excel CarthagoDom seront raccordés à l'application **après** validation des contrats de données.
3. Les preuves de signature/cachet signalent uniquement leur présence *apparente* ; Qwen ne peut certifier leur authenticité.
4. Les dates de contrat et permis peuvent différer dans certains cas réels (versions de documents, renouvellements) : les écarts sont bloqués, non corrigés automatiquement.
5. La règle d'augmentation et de proratisation n'est pas implémentée dans ce module. Elle est volontairement routée vers `A_VERIFIER` en attendant validation métier.
6. Les empreintes présentes dans le JSON sont supposées calculées par l'ingestion sécurisée. Le démonstrateur **ne calcule ni ne vérifie** physiquement les empreintes à partir des fichiers d'origine.
7. Le mécanisme `certify_dom` est un objet de démonstration. En production il faudra une identité authentifiée, séparation des rôles, audit externe non altérable, transactions, approbations et règles de validation définies avec les métiers / risques / DSI.
8. Aucun transfert, ordre SWIFT ou prélèvement CarthagoDom n'est généré par ce socle.

## Critère de réussite de la prochaine étape

Sur un corpus de domiciliation anonymisé et vérifié, avoir **zéro anomalie critique connue qui franchit les barrières** et une traçabilité permettant de retrouver la source PDF et la ligne CarthagoDom de chaque donnée certifiée. Ne pas confondre réussite sur tests synthétiques et validation métier en conditions réelles.

## Nouveauté V0.2 — Libellés CarthagoDom stricts

Le mapping CarthagoDom est maintenant centralisé dans **`config/carthagodom_columns.json`**.
Voir **`CONFIGURATION_CARTHAGODOM.md`** pour renseigner un libellé une seule fois.

- Adaptateur de lignes : `src/carthagodom_mapping.py` ; comparaison **exacte**, aucune variante ni détection floue.
- Le validateur DOM lie sa certification à l'empreinte du mapping ; changer un libellé impose une nouvelle validation.
- Les noms source encore inconnus (`reference_dom`, `compte_local`, `montant_total`, `statut_domiciliation`) sont laissés à `null` ; l'import certifiable reste bloqué jusqu'à configuration.
- Les scripts originaux V15-A ne sont pas modifiés ; la détection des variantes existant dans le notebook Partie 2 devra être contournée quand l'adaptateur sera raccordé à Domino.
- La preuve de validation MOCI ne peut pas être déduite d'une colonne hypothétique : elle doit être confirmée par une source réelle ou une validation habilitée distincte.

Test : `python -m unittest discover -s tests -v`.

## Mise à jour V0.3 — Fiche réelle CarthagoDom
La capture banque est une fiche **verticale** (libellés A, valeurs B) : `config/carthagodom_columns.json` correspond aux libellés exacts constatés. `src/carthagodom_vertical.py` lit les lignes sous ce format. En l’absence de compte complet et de statut de validation MOCI dans la capture, la certification et la génération de planning restent bloquées jusqu’à preuve indépendante. Voir `CONFIGURATION_CARTHAGODOM.md`.
