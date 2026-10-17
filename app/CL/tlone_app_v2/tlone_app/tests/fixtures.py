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
         CTS_DATE_DOCUMENT="02/01/2026", DOM_COMPTE_LOCAL_NORMALIZED="02700731010825900165",
         SIEGE_RACINE="07310108259", NUMERO_DOMICILIATION_PROPOSE="271901202614000123DZD",
         DQ_SCORE=88, AUGMENTATION_YEAR=None),
    # Augmentation 2026 du même DOM (mois paramétré = 4)
    dict(FICHIER="KAYA_AHMET_AUG_26.pdf", TYPE_DOSSIER="AUGMENTATION", DOSSIER_STATUS="REVIEW",
         CTS_DATE_DEBUT_VALIDITE_PERMIS="03/01/2026", CTS_DATE_FIN_VALIDITE_PERMIS="02/01/2028",
         CTS_SALAIRE_NET="350000.00", CTS_SALAIRE_NET_ANCIEN="328690.00", CTS_PART_TRANSFERABLE="332500.00",
         CTS_PART_PAYABLE_DZD="17500.00", CTS_NOM_PRENOM_TRAVAILLEUR="KAYA AHMET",
         CTS_NUMERO_PERMIS_TRAVAIL="31-00012345 / 26-01-000123", CTS_REFERENCE_DOCUMENT="CT-2026-0001",
         CTS_DATE_DOCUMENT="15/03/2026", DOM_COMPTE_LOCAL_NORMALIZED="02700731010825900165",
         SIEGE_RACINE="07310108259", NUMERO_DOMICILIATION_PROPOSE="271901202614000123DZD",
         DQ_SCORE=91, AUGMENTATION_YEAR=2026),
    # Dossier qui sera rejeté
    dict(FICHIER="DEMIR_ALI_CNT.pdf", TYPE_DOSSIER="NOUVEAU_CONTRAT", DOSSIER_STATUS="REVIEW",
         CTS_DATE_DEBUT_VALIDITE_PERMIS="01/02/2026", CTS_DATE_FIN_VALIDITE_PERMIS="31/01/2027",
         CTS_SALAIRE_NET="200000", CTS_PART_TRANSFERABLE="190000", CTS_NOM_PRENOM_TRAVAILLEUR="DEMIR ALI",
         DOM_COMPTE_LOCAL_NORMALIZED="02700731010826200186", SIEGE_RACINE="07310108262",
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
                periode="MARS 2026", compte_debiteur="02700731010825900165", beneficiaire_nom="KAYA AHMET",
                beneficiaire_compte="TR330006100519786457841326", swift="TEBUTRIS", banque_nom="TEB",
                date_demande="08/04/2026"),
     "ANNEXE_I": dict(nom_prenom="KAYA AHMET"),
     "ANNEXE_II": dict(mois_transfert="MARS 2026", nom_prenom="AHMET KAYA", compte_bancaire="02700731010825900165",
                       salaire_mensuel=328690.0, part_transferable=312255.0,
                       numero_domiciliation="27-19-01 2026.1 40 00123 DZD"),
     "BULLETIN": dict(nom_prenom="KAYA AHMET", mois_bulletin="MARS 2026", net_a_payer=328690.0)},
    # Non conforme : dépasse la part Annexe II et 95 % du net
    {"META": dict(fichier="07310-108259-202602.pdf", pages_trouvees="ANNEXE_I, ANNEXE_II, BULLETIN, OV"),
     "OV": dict(monnaie="DZD", montant_chiffres=320000.0, montant_lettres="TROIS CENT VINGT MILLE DINARS",
                periode="FEVRIER 2026", compte_debiteur="02700731010825900165", beneficiaire_nom="KAYA AHMET",
                beneficiaire_compte="TR33", swift="TEBUTRIS", banque_nom="TEB"),
     "ANNEXE_I": dict(nom_prenom="KAYA AHMET"),
     "ANNEXE_II": dict(mois_transfert="FEVRIER 2026", nom_prenom="KAYA AHMET",
                       compte_bancaire="02700731010825900165", salaire_mensuel=328690.0, part_transferable=312255.0),
     "BULLETIN": dict(nom_prenom="KAYA AHMET", mois_bulletin="FEVRIER 2026", net_a_payer=328690.0)},
    # À revoir : bulletin manquant, période partielle P1 de janvier (début 03/01)
    {"META": dict(fichier="07310-108259-202601P2.pdf", pages_trouvees="ANNEXE_I, ANNEXE_II, OV",
                  pages_manquantes="BULLETIN"),
     "OV": dict(monnaie="DZD", montant_chiffres=290000.0, montant_lettres=None, periode="JANVIER 2026 PART 2",
                compte_debiteur="02700731010825900165", beneficiaire_nom="KAYA AHMET", swift="TEBUTRIS"),
     "ANNEXE_II": dict(mois_transfert="JANVIER 2026", nom_prenom="KAYA AHMET", part_transferable=292110.0)},
    # Non rattaché (dossier DOM rejeté)
    {"META": dict(fichier="07310-108262-202605.pdf", pages_trouvees="ANNEXE_I, ANNEXE_II, BULLETIN, OV"),
     "OV": dict(monnaie="DZD", montant_chiffres=180000.0, montant_lettres="CENT QUATRE VINGT MILLE DINARS",
                periode="MAI 2026", compte_debiteur="02700731010826200186", beneficiaire_nom="DEMIR ALI",
                beneficiaire_compte="X", swift="X", banque_nom="X"),
     "ANNEXE_I": dict(nom_prenom="DEMIR ALI"),
     "ANNEXE_II": dict(mois_transfert="MAI 2026", nom_prenom="DEMIR ALI", salaire_mensuel=200000.0,
                       part_transferable=190000.0, compte_bancaire="02700731010826200186"),
     "BULLETIN": dict(nom_prenom="DEMIR ALI", mois_bulletin="MAI 2026", net_a_payer=200000.0)},
]


# --------------------------------------------------------------------------- CHAMPS_DETAIL (matrice)
PAGE_OF = {"ENGAGEMENT_DOMICILIATION": 1, "CONTRAT_TRAVAIL": 2, "CONTRAT_SPECIFIQUE": 3, "TITRE_TRAVAIL": 4}
PREFIX_DOC = {"DOM": "ENGAGEMENT_DOMICILIATION", "CTR": "CONTRAT_TRAVAIL", "CTS": "CONTRAT_SPECIFIQUE",
              "TTR": "TITRE_TRAVAIL"}


def _fields_for(d: dict) -> dict:
    """Valeurs lues par pièce (synthétiques), cohérentes avec DOSSIERS sauf anomalies voulues."""
    nom = d["CTS_NOM_PRENOM_TRAVAILLEUR"]
    deb, fin = d["CTS_DATE_DEBUT_VALIDITE_PERMIS"], d["CTS_DATE_FIN_VALIDITE_PERMIS"]
    sal, part = d["CTS_SALAIRE_NET"], d["CTS_PART_TRANSFERABLE"]
    mois = 24 if fin.endswith("2028") else 12
    compte = d.get("DOM_COMPTE_LOCAL_NORMALIZED") or "0270073101083000015"
    permis = d.get("CTS_NUMERO_PERMIS_TRAVAIL") or "31-00099999 / 26-01-000999"
    ref = d.get("CTS_REFERENCE_DOCUMENT") or "CT-2026-0099"
    f = {
        "DOM_NOM_RAISON_SOCIAL_CLIENT": nom, "DOM_COMPTE_LOCAL": compte, "DOM_NUMERO_CONTRAT": ref,
        "DOM_AGENCE_DOMICILIATAIRE": "AGENCE ORAN",
        "DOM_DUREE_CONTRAT_MOIS": str(mois), "DOM_DATE_DEBUT_CONTRAT": deb, "DOM_DATE_FIN_CONTRAT": fin,
        "DOM_SALAIRE_NET_MENSUEL": sal, "DOM_PART_TRANSFERABLE": part, "DOM_TAUX_TRANSFERABLE": "95",
        "DOM_MONTANT_TOTAL_DOMICILIE": f"{float(part) * mois:.2f}", "DOM_DATE_SIGNATURE": deb,
        "CTR_REFERENCE_DOCUMENT": ref, "CTR_DUREE_MOIS": str(mois), "CTR_DATE_DEBUT_CONTRAT": deb,
        "CTR_NOM_PRENOM_TRAVAILLEUR": nom, "CTR_NUMERO_PERMIS_TRAVAIL": permis,
        "CTR_DATE_DEBUT_VALIDITE_PERMIS": deb, "CTR_DATE_FIN_VALIDITE_PERMIS": fin, "CTR_SALAIRE_NET": sal,
        "CTR_REFERENCE_DOMICILIATION": d["NUMERO_DOMICILIATION_PROPOSE"],
        "CTR_SIGNATURE_TRAVAILLEUR_PRESENTE": "True", "CTR_SIGNATURE_EMPLOYEUR_PRESENTE": "True",
        "CTR_CACHET_EMPLOYEUR_PRESENT": "True",
        "CTS_REFERENCE_DOCUMENT": ref, "CTS_DUREE_MOIS": str(mois), "CTS_DATE_DEBUT_CONTRAT": deb,
        "CTS_NOM_PRENOM_TRAVAILLEUR": nom, "CTS_NUMERO_PERMIS_TRAVAIL": permis,
        "CTS_DATE_DEBUT_VALIDITE_PERMIS": deb, "CTS_DATE_FIN_VALIDITE_PERMIS": fin, "CTS_SALAIRE_NET": sal,
        "CTS_SALAIRE_NET_ANCIEN": d.get("CTS_SALAIRE_NET_ANCIEN"), "CTS_PART_TRANSFERABLE": part,
        "CTS_SIGNATURE_TRAVAILLEUR_PRESENTE": "True", "CTS_SIGNATURE_EMPLOYEUR_PRESENTE": "True",
        "CTS_CACHET_EMPLOYEUR_PRESENT": "True", "CTS_VISA_INSPECTION_TRAVAIL_PRESENT": "True",
        "TTR_NUMERO_PERMIS": permis, "TTR_NOM": nom.split()[0], "TTR_PRENOM": " ".join(nom.split()[1:]),
        "TTR_DATE_DEBUT": deb, "TTR_DATE_FIN": fin,
    }
    return f


# anomalies voulues : (champ, valeur normalisée, raw, confiance, statut DQ, motif)
FIELD_ANOMALIES = {
    "KAYA_AHMET_CNT.pdf": [("TTR_DATE_FIN", "02/01/2027", "02/01/2027", 94, "OK", None),
                           ("DOM_PART_TRANSFERABLE", "312255.00", "312:255:0O", 62, "OK", None)],
    "KAYA_AHMET_AUG_26.pdf": [("CTR_SIGNATURE_EMPLOYEUR_PRESENTE", "False", "False", 90, "OK", None)],
    "DEMIR_ALI_CNT.pdf": [("TTR_NOM", "DEMIR", "DEMIR", 91, "OK", None), ("TTR_PRENOM", "ALY", "ALY", 88, "OK", None)],
    "CELIK_MEHMET_CNT.pdf": [("DOM_COMPTE_LOCAL", "0270073101083000015", "0270 0731 0108 3000 015", 85, "REVIEW",
                              "COMPTE_LONGUEUR_INVALIDE (19 chiffres)")],
}
DOSSIER_EXTRA = {
    "KAYA_AHMET_CNT.pdf": dict(CARTHAGO_MATCH_STATUS="EXACT_DOMICILIATION_REFERENCE_MATCH", MODULO97_OK=True),
    "KAYA_AHMET_AUG_26.pdf": dict(CARTHAGO_MATCH_STATUS="EXACT_DOMICILIATION_REFERENCE_MATCH", MODULO97_OK=True),
    "DEMIR_ALI_CNT.pdf": dict(CARTHAGO_MATCH_STATUS="CLIENT_NOT_FOUND", MODULO97_OK=True),
    "CELIK_MEHMET_CNT.pdf": dict(CARTHAGO_MATCH_STATUS="EXACT_DOMICILIATION_REFERENCE_MATCH", MODULO97_OK=False,
                                 CLE_COMPTE="15", CLE_ATTENDUE_MOD97="—"),
}


def champs_detail() -> pd.DataFrame:
    rows = []
    for d in DOSSIERS:
        vals = _fields_for(d)
        an = {a[0]: a for a in FIELD_ANOMALIES.get(d["FICHIER"], [])}
        for champ, v in vals.items():
            doc = PREFIX_DOC[champ.split("_")[0]]
            norm, raw, conf, dq, why = v, v, 96, "OK", None
            if champ in an:
                _, norm, raw, conf, dq, why = an[champ]
            if v is None and champ not in an:
                dq = "MISSING"
            rows.append({"FICHIER": d["FICHIER"], "TYPE_DOSSIER": d["TYPE_DOSSIER"], "PAGE": PAGE_OF[doc],
                         "TYPE_DOCUMENT": doc, "CHAMP": champ, "RAW": raw, "NORMALIZED": norm,
                         "NORMALIZATION_STATUS": "AUTO_OK" if norm is not None else "MISSING",
                         "NORMALIZATION_RULE": "SYNTHETIQUE", "FIELD_CONFIDENCE": conf,
                         "FIELD_CONFIDENCE_LEVEL": "HIGH" if conf >= 90 else "MEDIUM" if conf >= 70 else "LOW",
                         "DQ_STATUS_FIELD": dq, "DQ_REASON": why, "DQ_IMPORTANCE": "STANDARD"})
    return pd.DataFrame(rows)


def carthago_match() -> pd.DataFrame:
    out = []
    for d in DOSSIERS:
        st = DOSSIER_EXTRA[d["FICHIER"]]["CARTHAGO_MATCH_STATUS"]
        if st == "CLIENT_NOT_FOUND":
            continue
        out.append({"FICHIER": d["FICHIER"], "SIEGE_RACINE": d["SIEGE_RACINE"], "CARTHAGO_CLIENT": d["SIEGE_RACINE"],
                    "CARTHAGO_NOM_COMPLET": d["CTS_NOM_PRENOM_TRAVAILLEUR"],
                    "CARTHAGO_NUM_DOM_RAW": d["NUMERO_DOMICILIATION_PROPOSE"], "REFERENCE_EXACT_MATCH": True,
                    "CARTHAGO_TYPE": "DOM"})
    return pd.DataFrame(out)


def specimen_pdf(path: Path, d: dict) -> None:
    """PDF de démonstration : une page par pièce, valeurs lues imprimées (aucune donnée réelle)."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # type: ignore
    vals = _fields_for(d)
    for champ, v, *_ in FIELD_ANOMALIES.get(d["FICHIER"], []):
        vals[champ] = v
    doc = fitz.open()
    for prefix, title in (("DOM", "ENGAGEMENT DE DOMICILIATION"), ("CTR", "CONTRAT DE TRAVAIL"),
                          ("CTS", "CONTRAT DE TRAVAIL SPECIFIQUE"), ("TTR", "TITRE DE TRAVAIL")):
        pg = doc.new_page()
        pg.insert_text((60, 70), "SPECIMEN — document fictif", fontsize=9, color=(0.6, 0, 0))
        pg.insert_text((60, 100), title, fontsize=15)
        y = 140
        for champ, v in vals.items():
            if champ.startswith(prefix + "_") and v is not None:
                pg.insert_text((60, y), f"{champ[len(prefix) + 1:].replace('_', ' ').title()} : {v}", fontsize=10)
                y += 20
    doc.save(path)


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
        pd.DataFrame([dict(d, **DOSSIER_EXTRA[d["FICHIER"]]) for d in DOSSIERS]) \
            .to_excel(w, sheet_name="DOSSIERS_A_VALIDER", index=False)
        pd.DataFrame([{"FICHIER": "KAYA_AHMET_CNT.pdf", "CONTROLE": "IDENTITE_CTS_CTR", "STATUT": "OK"}]) \
            .to_excel(w, sheet_name="CONTROLES_COHERENCE", index=False)
    champs_detail().to_csv(p.fields_csv, index=False, encoding="utf-8-sig")
    # export CarthagoDom avec les en-têtes réels (18/10/2026), sans le client DEMIR (non trouvé)
    pd.DataFrame([{"Accord pré-dom": None, "Agence": "AGENCE ORAN" if d["FICHIER"] != "CELIK_MEHMET_CNT.pdf"
                   else "AGENCE ARZEW", "Client": d["SIEGE_RACINE"], "Devise": "DZD",
                   "Nom complet": d["CTS_NOM_PRENOM_TRAVAILLEUR"], "Name": d["CTS_NOM_PRENOM_TRAVAILLEUR"],
                   "Numéro de domiciliation": d["NUMERO_DOMICILIATION_PROPOSE"]}
                  for d in DOSSIERS if d["FICHIER"] != "DEMIR_ALI_CNT.pdf"]).to_excel(p.carthago_xlsx, index=False)
    carthago_match().to_csv(p.carthago_match_csv, index=False, encoding="utf-8-sig")
    pd.DataFrame({"ANNEE_AUGMENTATION": [2026], "MOIS_AUGMENTATION": [4]}).to_excel(p.param_aug_xlsx, index=False)
    write_v26(p.tr_out / "audit_transferts_20261016_1200.xlsx", TRANSFERTS)
    pd.DataFrame([
        dict(NOM_PRENOM="KAYA AHMET", COMPTE="02700731010825900165", MOIS="2026-03", SALAIRE_NET=328690,
             IRG=0, MONTANT_TRANSFERABLE=312255, ATF_REFERENCE="ATF-03-2026"),
        dict(NOM_PRENOM="KAYA AHMET", COMPTE="02700731010825900165", MOIS="2026-02", SALAIRE_NET=328690,
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
    for d in DOSSIERS:
        specimen_pdf(p.dom_in / d["FICHIER"], d)
    for name, folder in [(t["META"]["fichier"], p.tr_in) for t in TRANSFERTS]:
        doc = fitz.open()
        for i in range(4):
            pg = doc.new_page()
            pg.insert_text((72, 100), f"SPECIMEN {name} — page {i + 1}", fontsize=14)
        doc.save(folder / name)
    return p


if __name__ == "__main__":
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/tlone_demo")).data_root)
