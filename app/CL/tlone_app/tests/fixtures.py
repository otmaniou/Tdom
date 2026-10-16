"""Jeu de données synthétique (aucune donnée réelle) pour tester sans GPU.

Construit l'arborescence /mnt/data attendue sous un dossier temporaire :
classeur Partie 2, paramètres d'augmentation, classeur v26 transferts, ATF,
autorisations. Utilisable aussi pour une démo :  python -m tests.fixtures /tmp/demo
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from tlone.config import Paths
from tlone.transfers import V26_SCHEMA

DOSSIERS = [
    # Nouveau contrat 03/01/2026 -> 02/01/2028, part 312 255.00
    dict(FICHIER="KAYA_AHMET_CNT.pdf", TYPE_DOSSIER="NOUVEAU_CONTRAT", DOSSIER_STATUS="REVIEW",
         CTS_DATE_DEBUT_VALIDITE_PERMIS="03/01/2026", CTS_DATE_FIN_VALIDITE_PERMIS="02/01/2028",
         CTS_SALAIRE_NET="328690.00", CTS_SALAIRE_NET_ANCIEN=None, CTS_PART_TRANSFERABLE="312255.00",
         CTS_PART_PAYABLE_DZD="16435.00", CTS_NOM_PRENOM_TRAVAILLEUR="KAYA AHMET",
         CTS_NUMERO_PERMIS_TRAVAIL="31-00012345 / 26-01-000123", CTS_REFERENCE_DOCUMENT="CT-2026-0001",
         CTS_DATE_DOCUMENT="02/01/2026", DOM_COMPTE_LOCAL_NORMALIZED="02700731010825900104",
         SIEGE_RACINE="07310108259", NUMERO_DOMICILIATION_PROPOSE="271901202614000123DZD",
         DQ_SCORE=88, AUGMENTATION_YEAR=None),
    # Augmentation 2026 du même DOM (mois paramétré = 4)
    dict(FICHIER="KAYA_AHMET_AUG_26.pdf", TYPE_DOSSIER="AUGMENTATION", DOSSIER_STATUS="REVIEW",
         CTS_DATE_DEBUT_VALIDITE_PERMIS="03/01/2026", CTS_DATE_FIN_VALIDITE_PERMIS="02/01/2028",
         CTS_SALAIRE_NET="350000.00", CTS_SALAIRE_NET_ANCIEN="328690.00", CTS_PART_TRANSFERABLE="332500.00",
         CTS_PART_PAYABLE_DZD="17500.00", CTS_NOM_PRENOM_TRAVAILLEUR="KAYA AHMET",
         CTS_NUMERO_PERMIS_TRAVAIL="31-00012345 / 26-01-000123", CTS_REFERENCE_DOCUMENT="CT-2026-0001",
         CTS_DATE_DOCUMENT="15/03/2026", DOM_COMPTE_LOCAL_NORMALIZED="02700731010825900104",
         SIEGE_RACINE="07310108259", NUMERO_DOMICILIATION_PROPOSE="271901202614000123DZD",
         DQ_SCORE=91, AUGMENTATION_YEAR=2026),
    # Dossier qui sera rejeté
    dict(FICHIER="DEMIR_ALI_CNT.pdf", TYPE_DOSSIER="NOUVEAU_CONTRAT", DOSSIER_STATUS="REVIEW",
         CTS_DATE_DEBUT_VALIDITE_PERMIS="01/02/2026", CTS_DATE_FIN_VALIDITE_PERMIS="31/01/2027",
         CTS_SALAIRE_NET="200000", CTS_PART_TRANSFERABLE="190000", CTS_NOM_PRENOM_TRAVAILLEUR="DEMIR ALI",
         DOM_COMPTE_LOCAL_NORMALIZED="02700731010826200111", SIEGE_RACINE="07310108262",
         NUMERO_DOMICILIATION_PROPOSE="271901202614000124DZD", DQ_SCORE=70),
    # Dossier avec ligne non décidée (compte manquant corrigé)
    dict(FICHIER="CELIK_MEHMET_CNT.pdf", TYPE_DOSSIER="NOUVEAU_CONTRAT", DOSSIER_STATUS="REVIEW",
         CTS_DATE_DEBUT_VALIDITE_PERMIS="15/01/2026", CTS_DATE_FIN_VALIDITE_PERMIS="14/01/2027",
         CTS_SALAIRE_NET="250000", CTS_PART_TRANSFERABLE="237500", CTS_NOM_PRENOM_TRAVAILLEUR="CELIK MEHMET",
         DOM_COMPTE_LOCAL_NORMALIZED=None, SIEGE_RACINE="07310108300",
         NUMERO_DOMICILIATION_PROPOSE="271901202614000125DZD", DQ_SCORE=60),
]

MANUAL = [
    dict(FICHIER="KAYA_AHMET_CNT.pdf", TYPE_DOSSIER="NOUVEAU_CONTRAT", PAGE=3, TYPE_DOCUMENT="CONTRAT_SPECIFIQUE",
         CHAMP="CTS_PART_TRANSFERABLE", RAW="312:255:00", NORMALIZED="312255.00", CONFIDENCE_QUALITE=72,
         NIVEAU_CONFIDENCE="MEDIUM", VALEUR_PROPOSEE="312255.00", DECISION_MANUELLE="VALIDEE"),
    dict(FICHIER="KAYA_AHMET_AUG_26.pdf", TYPE_DOSSIER="AUGMENTATION", PAGE=3, TYPE_DOCUMENT="CONTRAT_SPECIFIQUE",
         CHAMP="CTS_SALAIRE_NET", RAW="350 000", NORMALIZED="350000.00", VALEUR_PROPOSEE="350000.00",
         DECISION_MANUELLE="VALIDEE"),
    dict(FICHIER="DEMIR_ALI_CNT.pdf", TYPE_DOSSIER="NOUVEAU_CONTRAT", PAGE=4, TYPE_DOCUMENT="TITRE_TRAVAIL",
         CHAMP="TTR_DATE_FIN", RAW="31/01/2026", NORMALIZED="31/01/2026", DECISION_MANUELLE="REJETEE",
         COMMENTAIRE="Titre expiré"),
    dict(FICHIER="CELIK_MEHMET_CNT.pdf", TYPE_DOSSIER="NOUVEAU_CONTRAT", PAGE=1,
         TYPE_DOCUMENT="ENGAGEMENT_DOMICILIATION", CHAMP="DOM_COMPTE_LOCAL_NORMALIZED", RAW=None,
         NORMALIZED=None, VALEUR_PROPOSEE=None, DECISION_MANUELLE=None),
]

TRANSFERTS = [
    # Conforme : mars 2026 complet, avant augmentation (avril)
    {"META": dict(fichier="07310-108259-202603.pdf", pages_trouvees="ANNEXE_I, ANNEXE_II, BULLETIN, OV"),
     "OV": dict(monnaie="DZD", montant_chiffres=312255.0,
                montant_lettres="TROIS CENT DOUZE MILLE DEUX CENT CINQUANTE CINQ DINARS ALGERIENS",
                periode="MARS 2026", compte_debiteur="02700731010825900104", beneficiaire_nom="KAYA AHMET",
                beneficiaire_compte="TR330006100519786457841326", swift="TEBUTRIS", banque_nom="TEB",
                date_demande="08/04/2026"),
     "ANNEXE_I": dict(nom_prenom="KAYA AHMET"),
     "ANNEXE_II": dict(mois_transfert="MARS 2026", nom_prenom="AHMET KAYA", compte_bancaire="02700731010825900104",
                       salaire_mensuel=328690.0, part_transferable=312255.0,
                       numero_domiciliation="27-19-01 2026.1 40 00123 DZD"),
     "BULLETIN": dict(nom_prenom="KAYA AHMET", mois_bulletin="MARS 2026", net_a_payer=328690.0)},
    # Non conforme : dépasse la part Annexe II et 95 % du net
    {"META": dict(fichier="07310-108259-202602.pdf", pages_trouvees="ANNEXE_I, ANNEXE_II, BULLETIN, OV"),
     "OV": dict(monnaie="DZD", montant_chiffres=320000.0, montant_lettres="TROIS CENT VINGT MILLE DINARS",
                periode="FEVRIER 2026", compte_debiteur="02700731010825900104", beneficiaire_nom="KAYA AHMET",
                beneficiaire_compte="TR33", swift="TEBUTRIS", banque_nom="TEB"),
     "ANNEXE_I": dict(nom_prenom="KAYA AHMET"),
     "ANNEXE_II": dict(mois_transfert="FEVRIER 2026", nom_prenom="KAYA AHMET",
                       compte_bancaire="02700731010825900104", salaire_mensuel=328690.0, part_transferable=312255.0),
     "BULLETIN": dict(nom_prenom="KAYA AHMET", mois_bulletin="FEVRIER 2026", net_a_payer=328690.0)},
    # À revoir : bulletin manquant, période partielle P1 de janvier (début 03/01)
    {"META": dict(fichier="07310-108259-202601P2.pdf", pages_trouvees="ANNEXE_I, ANNEXE_II, OV",
                  pages_manquantes="BULLETIN"),
     "OV": dict(monnaie="DZD", montant_chiffres=290000.0, montant_lettres=None, periode="JANVIER 2026 PART 2",
                compte_debiteur="02700731010825900104", beneficiaire_nom="KAYA AHMET", swift="TEBUTRIS"),
     "ANNEXE_II": dict(mois_transfert="JANVIER 2026", nom_prenom="KAYA AHMET", part_transferable=292110.0)},
    # Non rattaché (dossier DOM rejeté)
    {"META": dict(fichier="07310-108262-202605.pdf", pages_trouvees="ANNEXE_I, ANNEXE_II, BULLETIN, OV"),
     "OV": dict(monnaie="DZD", montant_chiffres=180000.0, montant_lettres="CENT QUATRE VINGT MILLE DINARS",
                periode="MAI 2026", compte_debiteur="02700731010826200111", beneficiaire_nom="DEMIR ALI",
                beneficiaire_compte="X", swift="X", banque_nom="X"),
     "ANNEXE_I": dict(nom_prenom="DEMIR ALI"),
     "ANNEXE_II": dict(mois_transfert="MAI 2026", nom_prenom="DEMIR ALI", salaire_mensuel=200000.0,
                       part_transferable=190000.0, compte_bancaire="02700731010826200111"),
     "BULLETIN": dict(nom_prenom="DEMIR ALI", mois_bulletin="MAI 2026", net_a_payer=200000.0)},
]


def write_v26(path: Path, rows: list[dict]) -> None:
    """Reproduit la mise en page du create_excel du notebook v26."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Dossiers"
    cols = [(g, k, lab) for g, cs in V26_SCHEMA.items() for k, lab in cs]
    start = 1
    for g, cs in V26_SCHEMA.items():
        ws.cell(row=1, column=start, value=g)
        if len(cs) > 1:
            ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=start + len(cs) - 1)
        start += len(cs)
    for i, (_, _, lab) in enumerate(cols, 1):
        ws.cell(row=2, column=i, value=lab)
    for n, d in enumerate(rows, 3):
        for i, (g, k, _) in enumerate(cols, 1):
            ws.cell(row=n, column=i, value=d.get(g, {}).get(k))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def build(root: Path) -> Paths:
    p = Paths(Path(root))
    p.ensure()
    with pd.ExcelWriter(p.validation_xlsx, engine="openpyxl") as w:
        pd.DataFrame([{"FICHIER": d["FICHIER"], "TYPE_DOSSIER": d["TYPE_DOSSIER"], "DQ_SCORE": d["DQ_SCORE"]}
                      for d in DOSSIERS]).to_excel(w, sheet_name="DQ_DASHBOARD", index=False)
        man = pd.DataFrame(MANUAL)
        for c in ["CONTEXTE_VALIDATION", "SOURCE_PROPOSITION", "VALEUR_VALIDEE", "COMMENTAIRE", "DOSSIER_STATUS"]:
            if c not in man.columns:
                man[c] = None
        man.to_excel(w, sheet_name="A_VALIDER_MANUELLEMENT", index=False)
        pd.DataFrame(DOSSIERS).to_excel(w, sheet_name="DOSSIERS_A_VALIDER", index=False)
        pd.DataFrame([{"FICHIER": "KAYA_AHMET_CNT.pdf", "CONTROLE": "IDENTITE_CTS_CTR", "STATUT": "OK"}]) \
            .to_excel(w, sheet_name="CONTROLES_COHERENCE", index=False)
    pd.DataFrame({"ANNEE_AUGMENTATION": [2026], "MOIS_AUGMENTATION": [4]}).to_excel(p.param_aug_xlsx, index=False)
    write_v26(p.tr_out / "audit_transferts_20261016_1200.xlsx", TRANSFERTS)
    pd.DataFrame([
        dict(NOM_PRENOM="KAYA AHMET", COMPTE="02700731010825900104", MOIS="2026-03", SALAIRE_NET=328690,
             IRG=0, MONTANT_TRANSFERABLE=312255, ATF_REFERENCE="ATF-03-2026"),
        dict(NOM_PRENOM="KAYA AHMET", COMPTE="02700731010825900104", MOIS="2026-02", SALAIRE_NET=328690,
             IRG=0, MONTANT_TRANSFERABLE=312255, ATF_REFERENCE="ATF-02-2026"),
    ]).to_excel(p.atf_xlsx, index=False)
    pd.DataFrame([
        dict(NOM_PRENOM="KAYA AHMET", COMPTE=None, MOIS="MARS 2026", MONTANT_AUTORISE=312255,
             DATE_VALIDATION="01/04/2026", AUTORISATION_REFERENCE="AUT-2026-17"),
    ]).to_excel(p.autorisations_xlsx, index=False)
    # PDF factices pour l'aperçu
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # type: ignore
    for name, folder in [(d["FICHIER"], p.dom_in) for d in DOSSIERS] + \
                        [(t["META"]["fichier"], p.tr_in) for t in TRANSFERTS]:
        doc = fitz.open()
        for i in range(4):
            pg = doc.new_page()
            pg.insert_text((72, 100), f"SPECIMEN {name} — page {i + 1}", fontsize=14)
        doc.save(folder / name)
    return p


if __name__ == "__main__":
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/tlone_demo")).data_root)
