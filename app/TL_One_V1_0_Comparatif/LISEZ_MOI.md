# TL-One V1.0 — Comparatif métier CTS / DOM / CTR / TTR / Prédom

**Date : 16 octobre 2026.** Cette version **ne remplace ni ne modifie V0.9**. Elle exploite les 10 JSON RAW Qwen V15A déjà présents dans `data/json/` et le rapport de rapprochement V0.9. **Aucun GPU / réextraction Qwen requis.**

## Installer dans Domino

Décompresser `TL_One_V1_0_Comparatif.zip` dans le dossier existant :

```text
/mnt/TL_One_Test_Predom_V0_6/
  data/
    pdf/                            # déjà déposés
    json/                           # déjà déposés (RAW Partie 1)
    Demande_Predomiciliation.xlsx  # déjà présent
  resultats/
    rapprochement_v08.csv           # généré par V0.9 — NE PAS ÉCRASER
    rapport_rapprochement_v08.json
  rapprochement_v08.py             # V0.9 inchangé
  TL_One_V1_0_Comparatif/
    tl_one_v10.py
    app_v10.py
    vendor/part2_v15_A.ipynb
    config/champs_metier_base_v05.json
    tests/test_v10.py
```

Dans un terminal Domino :

```bash
cd /mnt/TL_One_Test_Predom_V0_6
python -m pip install -q pandas openpyxl
python -m unittest discover -s TL_One_V1_0_Comparatif/tests -v
python TL_One_V1_0_Comparatif/tl_one_v10.py --root .
```

Résultats dans `resultats/v10/` :

- `synthese_v10.csv` : 1 ligne par dossier, statuts techniques, nombre d'écarts, DQ.
- `comparatif_valeurs_v10.csv` : 1 ligne par champ métier × source (26 champs, cinq colonnes documentaires), normalisation, brut, page, scores Partie 1 et Partie 2, concordance.
- `comparatif_dossiers_v10.json` : données complètes d'infobulles, valeurs, scores, règles, anomalies P2 et sélection V0.9.
- `ecarts_cts_v10.csv` : écarts calculés **contre le CTS**, lorsque le CTS contient la référence correspondante.
- `champs_99_v15a.json` : détails complets des 99 champs du schéma P2, uniquement sur les pages effectivement présentes.
- `erreurs_v10.json` : incidents par dossier, sans interruption des autres dossiers. Code retour CLI = 2 en présence d'erreurs ; les rapports partiels restent consultables.

## Ouvrir l'interface de lecture seule (optionnelle)

```bash
python -m pip install -q streamlit pymupdf
streamlit run TL_One_V1_0_Comparatif/app_v10.py --server.address 0.0.0.0 --server.port 8501 -- --root .
```

Dans Domino, ouvrir le port 8501 via la fonctionnalité *App/preview/proxy* autorisée par l'équipe DSI. Le port est indicatif et peut être changé. **Ne pas rendre l'application accessible publiquement** : les résultats et PDF contiennent des données bancaires personnelles. L'application V1.0 est **consultative**, et ne stocke aucune décision utilisateur.

L'interface propose : liste des dossiers, filtre, matrice métier, infobulles par valeur (RAW, normalisé, score V15A P1/P2, règle, source/page, résultat), anomalies V15A et aperçu PDF. CA10 **absent**, cachet DOM **suspendu**.

## Règles métier conservées

1. **V0.9** identifie le client par les 11 derniers chiffres des 15 premiers chiffres du nom PDF et associe PDF/JSON par le nom complet. **V1.0 ne recalcule pas ni ne modifie ce rapprochement.**
2. `Request Decision Date` et `Statut` ont déjà servi à V0.9 pour proposer le dernier accord Prédom ; il reste **candidat à vérifier**, même si son nom ressemble au CTS.
3. `Référence` dans Prédom = **référence prédomiciliation**, pas numéro DOM. Un dossier « Accord Prédom » peut n'avoir aucun numéro DOM. Le numéro DOM n'est pas synthétisé. Le cachet est suspendu.
4. **CTS** = référence métier des données contractuelles qu'il contient. Les TTR restent des pièces officielles distinctes pour le permis, jamais corrigées automatiquement à partir du CTS.
5. La Partie 2 est réutilisée **en fonctions natives** depuis la copie du notebook V15A fourni, avec contrôle SHA256 et contrat RAW `DOM_EXTRACTION_V1` + `field_schema_hash` + `pipeline_version`. Les fonctions de normalisation, DQ, crosschecks, confidentes V15A ne sont pas réécrites.
6. Un seul bloc du notebook V15A est omis à l'exécution : les ASSERT de **démonstration** de sa cellule 18, qui utilisent `ACCOUNT_EXAMPLE` et échouent sur cette copie. Les fonctions de production de cette cellule sont exécutées intégralement. La cellule de *batch* et ses exports CarthagoDom ne sont pas lancés.
7. Scores P1 et P2 : **indices heuristiques opérationnels, pas probabilités d'exactitude**. Si une valeur n'a pas de score, on affiche `—`.
8. Si un champ est volontairement désactivé dans le profil TTR-7, l'état est `NON_EXTRAIT_VOLONTAIREMENT`, jamais un « 0 » de fiabilité inventé.
9. Des valeurs contradictoires entre plusieurs pages d'un même type de document produisent une alerte `VERSIONS_DIVERGENTES`, pas une sélection arbitraire.
10. **Aucune validation agence, aucun rejet bancaire, aucun contrôle automatique d'authenticité de signature, aucune création DOM, aucun cachet, aucun Planning TL** à ce stade.

## Points restant à confirmer sur les fichiers réels

- Ce livrable a été validé sur des **données synthétiques**, pas sur les 10 JSON réels stockés uniquement dans Domino.
- Le rapport V0.9 n'exporte que certaines colonnes Prédom. V1.0 ne peut donc pas inventer `Montant total`, contrat ou numéro officiel DOM à partir de cet export. Leur cellule affiche `NON_DISPONIBLE_V09`; enrichissement Prédom dans une version suivante.
- La mapping V0.5 contient 26 champs métier. Des règles de comparaison sont prudemment limitées à une même grandeur : aucune conversion salaire brut/net, aucune fusion référence CTS/CTR/Prédom, pas de date de fin de CTS artificiellement déduite.
- Une discordance documentaire n'est pas nécessairement une mauvaise extraction Qwen ; l'agent doit ouvrir la page et statuer.

## Plan à suivre

**V1.0** : valider les 10 JSON réels dans Domino et analyser synthèse/écarts/erreurs. **V1.1** : interface d'instruction agence avec décision par champ, justification, historisation et droits. **V1.2** : workflow validation DOM + confirmation CarthagoDom et gestion juridique du cachet. **V1.3** : Planning TL fondé sur les DOM confirmées.

Conserver le dossier de référence projet `TL_One_Dossier_Reference_2026-10-16.md` dans le dépôt GitHub Tdom.
