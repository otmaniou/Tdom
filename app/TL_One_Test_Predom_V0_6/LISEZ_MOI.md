# TL-One — Premier test terrain Prédom V0.6

**Ce kit n'est PAS encore l'App DOM demandée.** Il teste uniquement la lecture Prédom et la présélection du dernier accord admissible par client. Aucun OCR Qwen, aucune confrontation au CTS, aucune certification, aucune signature vérifiée ni apposition de cachet.

## Domino (environnement Python 3.11)

1. Décompresser le ZIP dans `/mnt` (dossier `/mnt/TL_One_Test_Predom_V0_6`).
2. Ouvrir le terminal :

```bash
cd /mnt/TL_One_Test_Predom_V0_6
python -m pip install openpyxl
python -m unittest discover -s tests -v
python predom_pilot.py data/predom_exemple_FICTIF.csv
```

3. Vérifier dans `resultats/selection_predom.csv` les clients et références proposés et dans `resultats/historique_predom.csv` toutes les références historiques.
4. Pour un export réel, copier l'Excel dans `/mnt/TL_One_Test_Predom_V0_6/data/`, **uniquement sur Domino**. Vérifier les noms d'en-têtes de l'Excel (une ligne par accord). Si nécessaire modifier `config_predom.json` : `colonnes`, `header_row`, `sheet_name`. Exécuter :

```bash
python predom_pilot.py data/mon_export_predom.xlsx
```

5. Vérifier les résultats sur cinq clients choisis manuellement (anciens accords, nouveaux accords, dates identiques, dates manquantes, statuts non admissibles). Les références proposées sont **à confronter au CTS** avant toute validation.

## Règles du pilote

- Statuts admissibles exacts : `Domicilié`, `Accord Prédom` (casse et espaces non significatifs pour les valeurs de statut seulement).
- Date utilisée : `Request Decision Date` (libellé colonne exact, sans alias).
- Si plusieurs références admissibles ont la même date maximale : `AMBIGUITE_MEME_DATE` (pas de sélection arbitraire).
- Une seule référence candidate par client. Si plusieurs CTS/contrats actifs, ce choix n'est **pas encore** une association définitive au bon contrat.
- Le champ `Référence` du workflow est distinct du `Numéro de domiciliation` officiel.
- CA10 : `ABSENT_NON_VERIFIE`; n'empêche pas les contrôles documentaires mais empêche d'affirmer une signature vérifiée sur cette base.
- Aucun contrôle d'authenticité de signature ni décision humaine simulés.
- Identifiants client et références DOM stockés comme **texte** dans Excel pour conserver les zéros initiaux. Les colonnes numériques suspectes ne sont pas sélectionnées automatiquement.

## Pour la vraie App

Fournir, dans le projet Domino uniquement : le fichier Excel Prédom réel (ou un extrait anonymisé avec vrais en-têtes), 5 à 10 dossiers PDF DOM/CTS/CTR/TTR et les sorties JSON V15A correspondantes. L'App interactive (comparatif valeurs normalisées, infobulles, PDF côte à côte, décisions humaines) reste à développer et ne doit pas être présentée comme déjà testable.
