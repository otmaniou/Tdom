# TL-One — Import CarthagoDom V0.4 : tableau horizontal

**Correction de l'hypothèse précédente : la capture envoyée par l'utilisateur était une présentation transposée manuellement pour faciliter la lecture. Le fichier d'origine est un Excel classique avec les libellés sur la première ligne et une domiciliation par ligne.**

Le module `src/carthagodom_vertical.py` a été supprimé, ainsi que ses tests. Le seul import conservé est `src/carthagodom_import.py`.

## Où changer un libellé une seule fois ?

`config/carthagodom_columns.json` : à droite des clés techniques, modifier le libellé exact de l'export. Les contrôles ne recherchent jamais d'alias. Aucun nom de colonne n'est renommé dans l'Excel source.

## Colonnes identifiées dans la capture transposée

`Client`, `Nom complet/Raison social`, `Numéro de domiciliation`, `Montant initial`, `Montant final`, `Total Financing Settlement Amount`, `Date domiciliation`, `Accord pré-dom`, `Invoices Date`, `Invoices Reference`, `Code bic` et autres champs indiqués dans la configuration.

**Attention** : orthographe des en-têtes et numéro de ligne exacts à confirmer en ouvrant l'export Excel d'origine, non encore fourni. La capture ne prouve pas un format de fichier vertical.

## Import massif tabulaire

```python
from carthagodom_import import load_horizontal_xlsx

lot = load_horizontal_xlsx('export_carthagodom.xlsx', employeur_id='TOSYALI')
print(lot['nb_lignes'])
for ligne in lot['lignes']:
    print(ligne['excel_row'], ligne['champs']['reference_dom'], ligne['anomalies_import'])
```

Cet import est un **prétraitement** ; il ne certifie pas les domiciliations. Il enregistre les identifiants de lignes et les empreintes de fichier et conserve les valeurs brutes. Pour les champs non démontrés (`compte_local`, `statut_domiciliation`) la certification reste bloquée. Les identifiants Excel stockés au format numérique sont signalés pour revue afin d'éviter une perte de zéro initial.

Le contrôle du cachet CTR, du CTS et du rapprochement bancaire reste à effectuer dans les autres composants TL-One.
