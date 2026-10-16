"""Lecture de fiche CarthagoDom en disposition verticale A=libellé, B=valeur.

Aucun alias ou recherche approchée. Le résultat sert à la PRÉVALIDATION,
pas à la certification, car la capture ne montre ni compte complet ni statut MOCI.
La prise en charge de campagnes multi-fiches doit être confirmée sur de vrais XLSX.
"""
from __future__ import annotations
from typing import Iterable, Any
from carthagodom_mapping import CarthagoMappingError


def extract_vertical(rows: Iterable[tuple[Any, Any]], config: dict) -> dict:
    pairs: dict[str, Any] = {}
    expected = {x for x in config["colonnes"].values() if x is not None} | set(config["libelles_supplementaires"].values())
    for idx, pair in enumerate(rows, 1):
        if len(pair) != 2:
            raise CarthagoMappingError(f"FORMAT_FICHE_INVALIDE: ligne {idx}")
        label, value = pair
        if not isinstance(label, str) or label not in expected:
            continue
        if label in pairs:
            raise CarthagoMappingError(f"LIBELLE_EN_DOUBLE: {label}")
        pairs[label] = value
    mandatory = [config['colonnes'][key] for key in ['client_code','nom_complet','reference_dom','montant_total']]
    missing = [x for x in mandatory if x not in pairs or pairs[x] is None or str(pairs[x]) == '']
    if missing:
        raise CarthagoMappingError('LIBELLES_OU_VALEURS_ABSENTS: '+ ', '.join(missing))
    canonical = {k: pairs.get(v) if v is not None else None for k,v in config['colonnes'].items()}
    return {
       'source_exacte':pairs,
       'donnees_preliminaires':canonical,
       'montants_distincts':{label:pairs.get(label) for label in [config['libelles_supplementaires']['montant_initial'], config['colonnes']['montant_total'], config['libelles_supplementaires']['total_financing_settlement_amount']]},
       'certification_autorisee':False,
       'obstacles_certification': ['COMPTE_LOCAL_ABSENT_SOURCE', 'PREUVE_VALIDATION_MOCI_ABSENTE_SOURCE'],
       'format':'FICHE_CARTHAGODOM_VERTICALE_AB',
    }


def extract_vertical_xlsx(xlsx_path, config, sheet_name=0) -> dict:
    """Fonction d'intégration ultérieure : lire XLSX réel après confirmation disposition."""
    import pandas as pd
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None, usecols='A:B', dtype=object, keep_default_na=False)
    return extract_vertical(list(df.itertuples(index=False, name=None)), config)
