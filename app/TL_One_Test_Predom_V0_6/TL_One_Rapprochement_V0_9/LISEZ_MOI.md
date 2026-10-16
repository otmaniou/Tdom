# TL-One — correctif consolidé V0.9

Corrige V0.8 sans intervention manuelle dans le script : configuration de `Request Decision Date`, détection des en-têtes avec espaces invisibles, dates Excel et dates texte via `predom_pilot._date`, identifiant client 11 chiffres issu des 15 premiers chiffres du compte, exclusion des `.ipynb_checkpoints`, absence de sélection en cas d’ex aequo.

## Installation Domino

Dans `/mnt/TL_One_Test_Predom_V0_6/`, sauvegarder les anciens scripts puis copier `rapprochement_v08.py`, `predom_pilot.py`, `config_predom.json` depuis cette archive. Ne pas déplacer `data/`.

## Commandes

```bash
python -m unittest discover -s tests -v
python rapprochement_v08.py --root . --predom data/Demande_Predomiciliation.xlsx
```

Les tests fournis sont dans le sous-dossier `tests` du ZIP. Copier ce sous-dossier si vous souhaitez les exécuter. Les rapports conservent les noms V08 pour compatibilité.

## Limites

Cette version réalise le rapprochement technique et propose une référence Prédom candidate, mais ne vérifie pas encore toutes les valeurs contractuelles du CTS. Le score de nom n’est pas une certification. Aucune validation bancaire, aucun cachet et aucune comparaison CA10. Les candidats ex aequo sont bloqués pour examen humain. Vérifier les lignes dont le statut est Domicilié avant d’assimiler une référence Prédom à une référence DOM.
