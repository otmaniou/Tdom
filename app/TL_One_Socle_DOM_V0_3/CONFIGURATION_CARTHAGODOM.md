# TL-One — Correspondance CarthagoDom V0.3

**Un seul emplacement pour changer les libellés : `config/carthagodom_columns.json`.**

## Source observée

La capture transmise montre **une fiche verticale à deux colonnes**, colonne A = libellé et colonne B = valeur. Ce n’est **pas** une table dont la première ligne contiendrait tous les noms de colonnes. L’existence d’autres exports en mode tableau reste à confirmer par le vrai fichier Excel.

Les libellés source sont recopiés sans alias. Les libellés essentiels :

- `Client`
- `Nom complet/Raison social` (sans « e » final dans la capture)
- `Numéro de domiciliation`
- `Montant initial`
- `Montant final`
- `Total Financing Settlement Amount`
- `Date domiciliation`
- `Accord pré-dom`
- `Invoices Date`, `Invoices Reference`, `Code bic`

Dans `colonnes`, **`montant_total` pointe vers `Montant final`**. Les deux autres montants sont définis dans `libelles_supplementaires`. Chaque libellé est enregistré **une seule fois**, et le lecteur compose la liste complète automatiquement.

## Sécurité : aucune certification sur la seule fiche

- Aucun numéro de compte complet visible : **`compte_local = null`** ; le code `Client` n’est pas un numéro de compte.
- Aucun statut de validation MOCI explicite : **`statut_domiciliation = null`**.
- `Situation d'apurement = Inconnu` et `Dom Documents Received = Non` ne prouvent pas la validation MOCI.
- Le lecteur `src/carthagodom_vertical.py` permet une lecture *préliminaire* des champs exacts, mais retourne `certification_autorisee = false`.
- L’ancien moteur de certification reste volontairement bloquant jusqu’à identification des sources permettant de confirmer compte bancaire et validation agence.

## Modifier un libellé

Corriger sa valeur en face de la clé technique, **dans ce seul fichier JSON**, après vérification sur le vrai XLSX. La vérification refuse les en-têtes incorrects, sans recherche d’alias. Toute modification change l’empreinte du mapping.

## Exemple de lecture après réception du fichier Excel original

```python
from carthagodom_mapping import load_mapping
from carthagodom_vertical import extract_vertical_xlsx

cfg = load_mapping('config/carthagodom_columns.json')
resultat = extract_vertical_xlsx('carthagodom_exemple.xlsx', cfg)
print(resultat['donnees_preliminaires'])
print(resultat['montants_distincts'])
```

Cette fonction suppose que le fichier réel suit bien le format vertical visible sur la capture. Il faudra vérifier sur un vrai XLSX et ne pas l'utiliser si le format diffère.
