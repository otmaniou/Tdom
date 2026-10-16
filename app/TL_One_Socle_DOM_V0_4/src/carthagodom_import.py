"""Import en masse CarthagoDom XLSX HORIZONTAL (une ligne = une domiciliation).

Les libellés sont fournis EXCLUSIVEMENT par config/carthagodom_columns.json.
Aucune recherche de variantes, aucune transformation des en-têtes source.

Import non certifiant : le compte bancaire complet et la preuve de validation
MOCI sont actuellement non identifiés dans l'extraction montrée.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Sequence

from carthagodom_mapping import CarthagoMappingError, check_headers, load_mapping, mapping_fingerprint


def extract_horizontal(headers: Sequence[Any], data_rows: Iterable[Sequence[Any]],
                       config: dict, *, employeur_id: str = "", source_sha256: str = "") -> dict:
    """Parse une table horizontale déjà chargée, avec contrôle STRICT des colonnes.

    Conserve les valeurs telles que lues ; ne reconstruit jamais une référence,
    un numéro de compte ou un statut absent. Rejette les cellules d'identifiants
    Excel numériques car zéros initiaux et précision peuvent être perdus.
    """
    cols = list(headers)
    check_headers(cols, config, require_ready=False)
    extra = config.get('libelles_supplementaires', {})
    mandatory = ('client_code', 'nom_complet', 'reference_dom', 'montant_total')
    required_sources = {k:config['colonnes'][k] for k in mandatory}
    missing_headers = [f"{k}: {label}" for k,label in required_sources.items() if label is None or label not in cols]
    if missing_headers:
        raise CarthagoMappingError('COLONNES_OBLIGATOIRES_ABSENTES: ' + ', '.join(missing_headers))

    if not employeur_id:
        raise CarthagoMappingError('EMPLOYEUR_OBLIGATOIRE: renseigner employeur_id')

    results=[]
    blanks=0
    for excel_row_no, values in enumerate(data_rows, start=int(config['format_source_observe'].get('header_row',1))+1):
        values=list(values)
        if len(values) != len(cols):
            raise CarthagoMappingError(f'NB_COLONNES_INCORRECT: ligne {excel_row_no}, {len(values)} valeurs pour {len(cols)} colonnes')
        if all(v is None or (isinstance(v,str) and not v.strip()) for v in values):
            blanks+=1
            continue
        source=dict(zip(cols,values))
        canonical={k:source.get(label) if label is not None else None for k,label in config['colonnes'].items()}
        additional={k:source.get(label) if label in source else None for k,label in extra.items()}
        anomalies=[]
        for k,label in required_sources.items():
            v=canonical.get(k)
            if v is None or (isinstance(v,str) and not v.strip()):
                anomalies.append('VALEUR_OBLIGATOIRE_ABSENTE:' + k)
        # Les champs bancaires sont des identifiants ; Excel peut perdre des zéros.
        for k in ('client_code','reference_dom','compte_local'):
            v=canonical.get(k)
            if isinstance(v,(int,float)) and not isinstance(v,bool):
                anomalies.append('IDENTIFIANT_EXCEL_NUMERIQUE_A_VERIFIER:' + k)
        # Le statut « Validée agence » n'est jamais déduit de la présence du dossier.
        if canonical.get('statut_domiciliation') is None:
            anomalies.append('STATUT_MOCI_NON_PROUVE')
        if canonical.get('compte_local') is None:
            anomalies.append('COMPTE_LOCAL_NON_PROUVE')
        results.append({
            'excel_row':excel_row_no,
            'record_id':f'{employeur_id}:{excel_row_no}',
            'employeur_id':employeur_id,
            'source_sha256':source_sha256,
            'champs':canonical,
            'champs_complementaires':additional,
            'anomalies_import':anomalies,
            'certification_autorisee':False,
        })
    return {
        'format':'CARTHAGODOM_HORIZONTAL',
        'employeur_id':employeur_id,
        'source_sha256':source_sha256,
        'en_tetes_source':cols,
        'mapping_version':config.get('version'),
        'lignes_vides_ignorees':blanks,
        'nb_lignes':len(results),
        'lignes':results,
        'certification_autorisee':False,
    }


def load_horizontal_xlsx(xlsx_path: str | Path, *, employeur_id: str,
                         config_path: str | Path | None = None, sheet_name: str | int = 0) -> dict:
    """Charge un export XLSX CarthagoDom tabulaire, sans nettoyer les entêtes.

    Un fichier d'origine réel est nécessaire pour confirmer le nom de feuille,
    la ligne d'en-tête et la façon dont Excel stocke les codes et références.
    """
    import pandas as pd

    cfg=load_mapping(config_path) if config_path is not None else load_mapping()
    path=Path(xlsx_path)
    if path.suffix.lower() not in ('.xlsx','.xlsm'):
        raise CarthagoMappingError('FORMAT_NON_AUTORISE: .xlsx ou .xlsm attendu')
    file_bytes=path.read_bytes()
    fingerprint=hashlib.sha256(file_bytes).hexdigest()
    header_row=int(cfg.get('format_source_observe',{}).get('header_row',1))
    if header_row < 1:
        raise CarthagoMappingError('CONFIG_INVALIDE: header_row doit être >= 1')
    frame=pd.read_excel(path,sheet_name=sheet_name,header=None,dtype=object,engine='openpyxl')
    if len(frame) < header_row:
        raise CarthagoMappingError('FICHIER_VIDE_OU_ENTETE_ABSENT')
    headers_raw=list(frame.iloc[header_row-1].values)
    if any(pd.isna(v) for v in headers_raw):
        raise CarthagoMappingError('EN_TETE_VIDE: vérifier que tous les en-têtes des colonnes utilisées sont renseignés')
    headers=list(headers_raw)
    rows=[]
    for row in frame.iloc[header_row:].itertuples(index=False,name=None):
        rows.append([None if pd.isna(v) else v for v in row])
    result=extract_horizontal(headers,rows,cfg,employeur_id=employeur_id,source_sha256=fingerprint)
    result['nom_fichier_source']=path.name
    result['nom_feuille_source']=sheet_name
    result['mapping_sha256']=mapping_fingerprint(config_path) if config_path is not None else mapping_fingerprint()
    return result
