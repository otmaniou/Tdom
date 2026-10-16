"""TL-One DOM V0.2 : gardes-fous de démonstration, indépendants de Qwen.

Cette couche n'approuve PAS les domiciliations bancaires et ne déclenche aucun transfert.
Elle consomme un objet canonique issu d'un adaptateur à construire sur les sorties
Partie 1 / Partie 2 V15-A et une ligne CarthagoDom déjà rapprochée.

Sécurité : fail-closed, champs OCR séparés de Carthago, Decimal, preuve par page,
certification humaine explicite et empreinte de révision des entrées.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from carthagodom_mapping import mapping_fingerprint

HERE = Path(__file__).resolve().parents[1]
POLICY = json.loads((HERE / 'config' / 'regles_dom_v0_1.json').read_text(encoding='utf-8'))
CATALOGUE = json.loads((HERE / 'schemas' / 'catalogue_champs_v15a.json').read_text(encoding='utf-8'))
KNOWN_FIELDS = {x for values in CATALOGUE['champs_par_type_document'].values() for x in values}

def canonical_sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()

def norm_digits(v: Any) -> str | None:
    if v is None or isinstance(v, bool): return None
    s = re.sub(r'[^0-9]', '', str(v))
    return s or None

def dom_ref_key(v: Any) -> str | None:
    """Comparaison alignée sur Partie 2 V15-A; n'est pas une preuve OCR."""
    s = norm_digits(v)
    return (s + 'DZD') if s else None

def strict_date(v: Any) -> date | None:
    if v is None: return None
    if isinstance(v, date) and not isinstance(v, datetime): return v
    s = str(v).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            d = datetime.strptime(s, fmt).date()
            if d.strftime(fmt) == s: return d
        except ValueError: pass
    return None

def strict_decimal(v: Any) -> Decimal | None:
    """L'adaptateur transmet la chaîne NORMALISÉE (ex. 350000.00)."""
    if v is None or isinstance(v, bool): return None
    s = str(v).strip()
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', s): return None
    try:
        d = Decimal(s)
        return d if d.is_finite() else None
    except InvalidOperation: return None

def normalized_person(v: Any) -> str | None:
    if not v: return None
    # Nettoyage mineur ; ne substitue PAS une équivalence d'identité réglementaire.
    s = re.sub(r'\s+', ' ', str(v).strip().upper())
    return s or None

def issue(code: str, severity: str, context: str, detail: str) -> dict:
    return {'code':code,'severity':severity,'context':context,'detail':detail}

def _value(dossier: dict, field: str) -> Any:
    f = dossier.get('fields', {}).get(field)
    return f.get('normalized') if isinstance(f, dict) else None

def validate_dom(dossier: dict) -> dict:
    """Contrôles bloquants : aucune inférence / complétion des pièces manquantes."""
    alerts: list[dict] = []
    def add(code,severity,context,detail): alerts.append(issue(code,severity,context,detail))

    if not isinstance(dossier, dict):
        return {'status':'BLOQUE', 'issues':[issue('INVALID_INPUT','BLOQUANT','dossier','Entrée non objet')], 'review_required':True, 'revision_sha256':None}
    rev = canonical_sha({'payload':dossier, 'policy_version':POLICY['version'], 'field_schema_hash':CATALOGUE['schema_sha256'], 'bank_column_mapping_hash':mapping_fingerprint()})
    for k in ('employeur_id','campagne_id','document_sha256','pipeline_version'):
        if not dossier.get(k): add('METADATA_MISSING','BLOQUANT',k,'Métadonnée obligatoire absente')
    if not re.fullmatch(r'[a-f0-9]{64}',str(dossier.get('document_sha256') or '')):
        add('PDF_SHA_INVALID','BLOQUANT','document_sha256','Empreinte PDF absente ou invalide')
    if dossier.get('type_dossier') not in ('NOUVEAU_CONTRAT','AUGMENTATION','RENOUVELLEMENT'):
        add('DOSSIER_TYPE_UNRESOLVED','BLOQUANT','type_dossier','Type non validé')
    docs = dossier.get('documents') or []
    for t in POLICY['mandatory_documents']:
        if t not in docs: add('DOCUMENT_MISSING','BLOQUANT',t,'Pièce attendue absente ou non reconnue')
    fields = dossier.get('fields') or {}
    for f in fields:
        if f not in KNOWN_FIELDS: add('UNKNOWN_FIELD','REVIEW',f,'Champ absent du schéma V15-A : vérifier adaptateur')
    must = list(POLICY['critical_fields'])
    if dossier.get('type_dossier') == 'NOUVEAU_CONTRAT':
        must += POLICY['additional_critical_new_contract']
    for name in must:
        f = fields.get(name)
        if not isinstance(f, dict) or f.get('normalized') is None or f.get('raw') is None:
            add('CRITICAL_UNREADABLE','BLOQUANT',name,'Aucune valeur vérifiable dans la pièce source')
            continue
        if not isinstance(f.get('page'),int) or f['page'] < 1:
            add('NO_PAGE_EVIDENCE','REVIEW',name,'Page d’origine non fournie')
        if f.get('needs_review') is not False:
            add('EXTRACTION_UNCERTAIN','REVIEW',name,'Extraction incertaine ou non qualifiée')
        prefix = name.split('_')[0]
        expected = {'DOM':'ENGAGEMENT_DOMICILIATION','CTR':'CONTRAT_TRAVAIL','CTS':'CONTRAT_SPECIFIQUE','TTR':'TITRE_TRAVAIL'}[prefix]
        if f.get('document_type') != expected:
            add('BAD_FIELD_PROVENANCE','BLOQUANT',name,'Origine documentaire incohérente')

    # Les valeurs comptables sont transmises par un référentiel distinct de Qwen.
    bank = dossier.get('carthago_dom') or {}
    if bank.get('column_mapping_sha256') != mapping_fingerprint():
        add('BANK_COLUMN_MAPPING_VERSION_MISMATCH','BLOQUANT','carthago_dom.column_mapping_sha256',
            'Mapping non traçable ou différent de la configuration actuelle : importer à nouveau')
    for k in POLICY['carthagodom_required']:
        if bank.get(k) is None or bank.get(k)=='':
            add('BANK_SOURCE_MISSING','BLOQUANT',k,'Extraction CarthagoDom incomplète')
    if not re.fullmatch(r'[a-f0-9]{64}',str(bank.get('snapshot_sha256') or '')):
        add('BANK_SNAPSHOT_SHA_INVALID','BLOQUANT','carthago_dom.snapshot_sha256','Empreinte de l’extraction bancaire non vérifiable')
    if bank.get('employeur_id') != dossier.get('employeur_id'):
        add('EMPLOYER_BANK_SCOPE_MISMATCH','BLOQUANT','carthago_dom.employeur_id','Enregistrement bancaire hors du périmètre employeur sélectionné')
    if bank.get('validation_agence_confirmee') is not True:
        add('BANK_NOT_VALIDATED','BLOQUANT','carthago_dom','Validation agence non confirmée dans la source bancaire')
    if bank.get('match_cardinality') != 1:
        add('BANK_MATCH_NOT_UNIQUE','BLOQUANT','carthago_dom','Aucun ou plusieurs enregistrements CarthagoDom correspondants')

    # CTR tampon : seule preuve documentaire de la référence dans ce contrôle.
    raw_ctr = (fields.get('CTR_REFERENCE_DOMICILIATION') or {}).get('raw')
    raw_bank_ref = bank.get('reference_dom')
    if not raw_ctr or not raw_bank_ref:
        add('DOM_REFERENCE_ABSENT','BLOQUANT','CTR / CarthagoDom','Référence cachet ou référence bancaire manquante')
    elif dom_ref_key(raw_ctr) != dom_ref_key(raw_bank_ref):
        add('DOM_REFERENCE_MISMATCH','BLOQUANT','CTR / CarthagoDom','Référence du cachet CTR différente de CarthagoDom')
    # Le normalisé OCR et le raw doivent aussi rester cohérents.
    ctr_norm = _value(dossier, 'CTR_REFERENCE_DOMICILIATION')
    if raw_ctr and ctr_norm and dom_ref_key(raw_ctr) != dom_ref_key(ctr_norm):
        add('CTR_REF_NORMALIZATION_MISMATCH','BLOQUANT','CTR_REFERENCE_DOMICILIATION','Valeur normalisée contradictoire avec le RAW OCR')

    raw_local = _value(dossier, 'DOM_COMPTE_LOCAL')
    bank_local = bank.get('compte_local')
    if not raw_local or not bank_local:
        add('ACCOUNT_MISSING','BLOQUANT','DOM / CarthagoDom','Compte incomplet')
    elif norm_digits(raw_local) != norm_digits(bank_local):
        add('ACCOUNT_MISMATCH','BLOQUANT','DOM / CarthagoDom','Compte local différent du compte CarthagoDom')
    if raw_local and len(norm_digits(raw_local) or '') != 20:
        add('ACCOUNT_FORMAT_REVIEW','REVIEW','DOM_COMPTE_LOCAL','Compte différent de 20 chiffres : contrôler le format applicable')

    # Dates contractuelles : comparaison informative mais écart bloquant jusqu'à justification.
    start_pairs = [('DOM_DATE_DEBUT_CONTRAT','CTS_DATE_DEBUT_VALIDITE_PERMIS')]
    end_pairs = [('DOM_DATE_FIN_CONTRAT','CTS_DATE_FIN_VALIDITE_PERMIS')]
    for a,b in start_pairs + end_pairs:
        va,vb = strict_date(_value(dossier,a)),strict_date(_value(dossier,b))
        if va is None or vb is None:
            add('INVALID_DATE','BLOQUANT',f'{a} / {b}','Date absente ou non interprétable de façon déterministe')
        elif va != vb:
            add('DATES_MISMATCH','BLOQUANT',f'{a} / {b}','Divergence entre dates DOM et CTS à investiguer')
    for f, ref in [('CTR_DATE_DEBUT_VALIDITE_PERMIS','CTS_DATE_DEBUT_VALIDITE_PERMIS'),
                   ('CTR_DATE_FIN_VALIDITE_PERMIS','CTS_DATE_FIN_VALIDITE_PERMIS'),
                   ('TTR_DATE_DEBUT','CTS_DATE_DEBUT_VALIDITE_PERMIS'),
                   ('TTR_DATE_FIN','CTS_DATE_FIN_VALIDITE_PERMIS')]:
        x,y=strict_date(_value(dossier,f)),strict_date(_value(dossier,ref))
        if x is None or y is None:
            add('SUPPORTING_DATE_MISSING','REVIEW',f'{f} / {ref}','Date absente ou illisible : comparaison nécessaire')
        elif x != y:
            add('SUPPORTING_DATE_MISMATCH','BLOQUANT',f'{f} / {ref}','Dates différentes entre les pièces : vérifier la version documentaire')
    ds,de = strict_date(_value(dossier,'DOM_DATE_DEBUT_CONTRAT')),strict_date(_value(dossier,'DOM_DATE_FIN_CONTRAT'))
    if ds and de and ds > de: add('CONTRACT_INVALID_INTERVAL','BLOQUANT','DOM','Date fin antérieure à date début')

    # La part transférable doit avoir un sens contractuel et ne jamais dépasser le net.
    net = strict_decimal(_value(dossier,'CTS_SALAIRE_NET'))
    part = strict_decimal(_value(dossier,'CTS_PART_TRANSFERABLE'))
    if net is None or part is None:
        add('INVALID_FINANCIAL_AMOUNT','BLOQUANT','CTS','Salaire net ou part transférable non normalisé au format décimal sûr')
    elif part <= 0 or net <= 0 or part > net:
        add('CTS_TRANSFERABLE_INVALID','BLOQUANT','CTS','Part transférable nulle, négative ou supérieure au net')
    if dossier.get('type_dossier') == 'NOUVEAU_CONTRAT':
        dom_part = strict_decimal(_value(dossier,'DOM_PART_TRANSFERABLE'))
        dom_total = strict_decimal(_value(dossier,'DOM_MONTANT_TOTAL_DOMICILIE'))
        if dom_part is None or dom_total is None:
            add('DOM_FINANCIAL_UNREADABLE','BLOQUANT','DOM','Part ou montant total non disponible')
        elif part is not None and dom_part != part:
            add('DOM_CTS_PART_MISMATCH','BLOQUANT','DOM / CTS','Part transférable différente entre DOM et CTS')
        bank_total = bank.get('montant_total')
        if bank_total is None or strict_decimal(bank_total) is None:
            add('BANK_TOTAL_MISSING','REVIEW','carthago_dom.montant_total','Montant total bancaire absent ou format non sûr')
        elif dom_total is not None and strict_decimal(bank_total) != dom_total:
            add('DOM_BANK_TOTAL_MISMATCH','BLOQUANT','DOM / CarthagoDom','Montant total DOM différent du montant bancaire')
    else:
        add('VERSION_RULES_REVIEW','REVIEW','type_dossier','Les règles d’augmentation/renouvellement nécessitent une validation de version contractuelle')

    dom_name = normalized_person(_value(dossier,'CTR_NOM_PRENOM_TRAVAILLEUR'))
    cts_name = normalized_person(_value(dossier,'CTS_NOM_PRENOM_TRAVAILLEUR'))
    if dom_name and cts_name and dom_name != cts_name:
        add('NAME_MISMATCH','BLOQUANT','CTR / CTS','Identités différentes après suppression des espaces superflus')
    name_dom=normalized_person(_value(dossier,'DOM_NOM_RAISON_SOCIAL_CLIENT'))
    if name_dom is None:
        add('DOM_PERSON_MISSING','REVIEW','DOM','Nom du titulaire absent, vérification nécessaire')
    elif dom_name and name_dom != dom_name:
        add('DOM_PERSON_MISMATCH','REVIEW','DOM / CTR','Titulaire DOM différent du titulaire CTR : contrôle humain nécessaire')
    ttr_nom=normalized_person(_value(dossier,'TTR_NOM'))
    ttr_prenom=normalized_person(_value(dossier,'TTR_PRENOM'))
    if dom_name and ttr_nom and ttr_prenom and dom_name != f'{ttr_nom} {ttr_prenom}':
        add('TTR_NAME_VARIATION','REVIEW','CTR / TTR','Écart possible nom/prénom ou ordre ; vérification documentaire nécessaire')
    for f in ('CTR_SIGNATURE_TRAVAILLEUR_PRESENTE','CTR_SIGNATURE_EMPLOYEUR_PRESENTE',
              'CTR_CACHET_EMPLOYEUR_PRESENT','CTS_SIGNATURE_TRAVAILLEUR_PRESENTE',
              'CTS_SIGNATURE_EMPLOYEUR_PRESENTE','CTS_CACHET_EMPLOYEUR_PRESENT'):
        val=_value(dossier,f)
        if val is not True:
            add('SIGNATURE_OR_STAMP_NOT_CONFIRMED','REVIEW',f,'Présence non confirmée ; Qwen ne garantit pas l’authenticité des signatures/cachets')

    bank_name=normalized_person(bank.get('nom_complet'))
    if bank_name is None:
        add('BANK_NAME_MISSING','REVIEW','carthago_dom.nom_complet','Nom salarié indisponible dans la source bancaire')
    elif dom_name and bank_name != dom_name:
        add('BANK_NAME_MISMATCH','REVIEW','CTR / CarthagoDom','Écart de nom à vérifier manuellement, sans substitution automatique')
    blocked = any(x['severity']=='BLOQUANT' for x in alerts)
    status = 'BLOQUE' if blocked else ('A_VERIFIER' if alerts else 'CONTROLE_OK')
    return {
        'employeur_id':dossier.get('employeur_id'),
        'campagne_id':dossier.get('campagne_id'),
        'revision_sha256':rev,
        'rules_version':POLICY['version'],
        'status':status,
        'review_required':bool(alerts),
        'issues':alerts,
        'planning_definitif_autorise':False,
        'note':'CONTROLE_OK ne constitue PAS une certification métier.'
    }

def certify_dom(dossier: dict, assessment: dict, reviewer_id: str, justification: str) -> dict:
    """Certificat de démonstration : exige 0 écart, révision identique et revue humaine."""
    updated = validate_dom(dossier)
    if assessment.get('revision_sha256') != updated['revision_sha256']:
        raise ValueError('Données modifiées depuis le contrôle : réévaluation requise')
    if updated['status'] != 'CONTROLE_OK' or updated['issues']:
        raise ValueError('Certification impossible : anomalies ou contrôles à revoir')
    if not reviewer_id.strip() or not justification.strip():
        raise ValueError('Identité du valideur et justification requises')
    return {
        'status':'CERTIFIE_TL_ONE',
        'revision_sha256':updated['revision_sha256'],
        'rules_version':updated['rules_version'],
        'reviewer_id':reviewer_id,
        'justification':justification,
        'validated_at_utc':datetime.now(timezone.utc).isoformat(),
        'planning_definitif_autorise':True,
        'note':'Validation interne TL-One, distincte de la validation réglementaire dans CarthagoDom.'
    }

def may_generate_planning(dossier: dict, certificate: dict) -> bool:
    """La présence d'un certificat ne suffit pas : revue + données courantes identiques."""
    result=validate_dom(dossier)
    return bool(
        certificate.get('status')=='CERTIFIE_TL_ONE'
        and result['status']=='CONTROLE_OK'
        and certificate.get('revision_sha256')==result['revision_sha256']
        and certificate.get('rules_version')==result['rules_version']
        and certificate.get('reviewer_id')
        and certificate.get('validated_at_utc')
    )

if __name__ == '__main__':
    import argparse
    ap=argparse.ArgumentParser(description='Évaluer un dossier DOM canonique sans Qwen')
    ap.add_argument('dossier_json',type=Path)
    args=ap.parse_args()
    dossier=json.loads(args.dossier_json.read_text(encoding='utf-8'))
    print(json.dumps(validate_dom(dossier),ensure_ascii=False,indent=2))
