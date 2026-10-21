# TL-One — Démonstration au CEO (≈ 15 minutes)

Message clé : **un processus manuel, multi-outils et à risque devient un parcours guidé où l'IA lit les pièces,
TL-One contrôle et prépare, et chaque acteur ne tranche que les écarts — pour plusieurs employeurs.**

## Préparation (la veille)
1. `cp -r /mnt/code/tlone_app_v3 /mnt/code/tlone_app_v4`, coller les fichiers V4, puis
   `cd /mnt/code/tlone_app_v4 && python3 verifier_copie.py --reparer` → 60/60 ; `/mnt/code/app.sh` pointe sur v4.
2. Relancer l'App (Domino → App → Restart). Le worker GPU n'est pas nécessaire pour la démo.
3. Page **Employeurs** → bouton **« Créer / réinitialiser l'employeur de démonstration »** (≈ 5 s).
   Jeu entièrement fictif : 12 salariés, 13 DOM, base RH / ATF / autorisations du mois (page du portail),
   14 OV lus, une extraction OV d'un mois passé, historique CarthagoTrade / Atlas, blocages et soldes.
4. Garder sous la main les 3 fichiers BOCI préparés à la main (spécimens) pour l'étape 7.
5. Option « IA en direct » : lancer le worker GPU et préparer 1 ou 2 PDF d'OV spécimens (TOSYALI).

## Déroulé
| # | Écran | Ce que l'on montre | Phrase clé |
|---|---|---|---|
| 1 | **Accueil** (employeur DEMO) | Bandeau, 6 indicateurs, parcours en 11 étapes (vert = TL-One, gris = autres acteurs), avant / après | « Tout le parcours d'un TL sur une seule page, de la DOM scannée au débit Atlas. » |
| 2 | **Domiciliations** → ② Dossiers | 13 dossiers lus par l'IA ; 2 écarts à arbitrer (date du permis ≠ CTS ; part illisible) ; ouvrir un dossier : valeur lue à côté de la page source | « L'IA lit, l'analyste ne tranche que les 2 écarts au lieu de relire 13 dossiers. » |
| 3 | **Planning TL** → ④ Planning × base RH | La base RH du mois face aux DOM : YAVUZ — PART 2 (nouveau contrat du 18) **non domiciliée** | « TL-One voit avant la banque qu'une nouvelle DOM est à créer. » |
| 4 | **Transferts OV** → ② Référentiels | Base RH (contrôle qualité : RIB, IBAN, SWIFT, 95 % × net × jours/30), ATF, **autorisations = la page du portail telle quelle** : NIF contrôlé, total de la demande retrouvé, 12 articles | « On dépose la page du portail : TL-One la lit et la contrôle, sans ressaisie. » |
| 5 | **Transferts OV** → ③ Dossiers | 14 OV, 4 à traiter. Ouvrir **KAPLAN** : IBAN de l'OV ≠ base RH (1 chiffre). Ouvrir **GUNES** : OV de 25 000 DZD au-dessus de la part (6 plafonds en rouge). Valider en direct un dossier conforme | « Chaque OV passe 20+ contrôles en une seconde ; l'humain ne voit que les exceptions. » |
| 6 | **Transferts OV** → ④ Vigilance | Deux HIT. **SAHIN** (bénéficiaire = épouse) : déjà analysé « non avéré » le mois dernier → TL-One le reconnaît, affiche l'analyse précédente et propose **♻️ Reconduire** (tracé comme reconduction). **PATEL** (banque HDFC) : nouvelle alerte → analyse en direct « non avéré » + commentaire ; la fiche annotée est archivée et l'alerte bancaire sera reconnue pour tous les clients le mois suivant. Onglet Suivi : registre des alertes analysées | « Un faux positif analysé une fois n'est plus jamais ré-analysé à l'aveugle : on sait qui l'a traité, quand et pourquoi. » |
| 7 | **Historique TL** → ② TL à exécuter | 4 prêts, 1 à bloquer (fichier de blocages pour l'agence), 1 solde insuffisant (le compte ne devient jamais débiteur), 1 anomalie (« Exécuté » sans débit Atlas) ; fichier pour l'employeur | « La règle solde − Σ(TL + 5 000) ≥ 0 est appliquée automatiquement. » |
| 8 | **Historique TL** → ③ Anomalies / ④ Planning × TL | Double débit Atlas (critique), reliquats à régulariser avec leur montant | « Les doubles transferts et les reliquats ne passent plus inaperçus. » |
| 8b | **Historique TL** → ⑤ Régularisation | Chaque mois non transféré a son **motif** : SHARMA mai = OV rejeté, juin = dossier jamais scanné + absent de l'ATF ; TASKIN = « Exécuté » sans débit Atlas ; et le contrôle a posteriori des TL exécutés (ERDEM : débité deux fois) | « Sur nos 12 000 TL passés, on sait enfin pourquoi un mois n'est pas parti — et ce qui est parti de trop. » |
| 9 | **Fichiers BOCI** → ① | 3 fichiers Trade / DOM / Règlement générés (date valeur laissée vide pour le BOCI ; « Name CLIENT » = base RH), contrôle automatique : 0 écart ; archivage | « Les 3 fichiers sortent d'une seule ligne par TL : cohérents par construction. » |
| 10 | **Fichiers BOCI** → ③ Contrôler des fichiers | Déposer les 3 fichiers préparés à la main : **7 bloquants + 20 points à vérifier** (IBAN de 25 caractères, IBAN différent entre Trade et Règlement, période incohérente entre fichiers, compte correspondant EUR manquant…) | « Voilà ce que TL-One évite à chaque envoi. » |
| 11 | **Employeurs** | Recherche par raison sociale / NIF, création d'un employeur en 2 champs, sélecteur en haut à gauche | « Le même outil sert tous nos employeurs. » |

## Questions probables
- **Fiabilité de l'IA ?** Toute valeur illisible ou incohérente part en revue humaine ; aucune décision automatique
  de rejet ; chaque correction est journalisée (qui, quand, pourquoi).
- **Données ?** Tout reste dans Domino (BNP), dataset restreint ; modèles hébergés en interne ; App en accès restreint.
- **Réglementaire ?** Le TL s'exécute sur la base de l'OV ; la base RH, l'ATF et l'autorisation le contrôlent ;
  plafonds et cumul DOM vérifiés avant le BOCI.
- **Et ensuite ?** Contrôle post-injection (fichiers transmis ↔ extraction après la prod), e-mail aux salariés,
  RPA Atlas à date valeur : TL-One produit déjà les fichiers et rapproche l'historique Atlas.
