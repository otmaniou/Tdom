# TL-One V0.8 — rapprochement de test

Copier `rapprochement_v08.py` et `config_predom.json` dans `/mnt/TL_One_Test_Predom_V0_6/`. Garder les PDF dans `data/pdf`, les JSON dans `data/json` et Excel dans `data/`.

```bash
cd /mnt/TL_One_Test_Predom_V0_6
python rapprochement_v08.py --root . --predom data/Demande_Predomiciliation.xlsx
```

**IMPORTANT** : dans `config_predom.json`, `client_id` est initialement `Client` selon la capture du terminal, et `predom_reference` est `Référence`. Si le fichier dispose réellement de `Identifiant client` comme colonne, changer seulement la valeur `client_id`. `decision_date` vaut `null` car `Request Decision Date` n'est pas dans les en-têtes visibles : la sélection de la dernière référence reste alors BLOQUÉE, pas devinée. Configurer la vraie colonne dès qu'elle est disponible.

Le nom du PDF doit suivre `<DOM_compte_local>-AAAAMM-dom-<nom>.pdf`; l'identifiant est `compte[:15][-11:]`. Comparaison exacte des identifiants, contrôle du compte lu par Qwen et score du nom `CTS_NOM_PRENOM_TRAVAILLEUR` contre Prédom. Association PDF-JSON uniquement par même nom de base ; si les JSON portent un autre nom, le rapport les signale sans inventer de correspondance. Aucun rapprochement par simple proximité de nom de fichier.

Résultats : `resultats/rapprochement_v08.csv` et `resultats/rapport_rapprochement_v08.json`. Le CA10 reste absent et le cachet suspendu. Les PDF/JSON réels restent dans Domino.
