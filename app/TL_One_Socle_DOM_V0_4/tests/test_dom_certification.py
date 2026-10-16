import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
from dom_certification import validate_dom, certify_dom, may_generate_planning
from carthagodom_mapping import mapping_fingerprint


def sample():
    docs=['ENGAGEMENT_DOMICILIATION','CONTRAT_TRAVAIL','CONTRAT_SPECIFIQUE','TITRE_TRAVAIL']
    fields={}
    def f(key,val,doc):
        fields[key]={'raw':str(val),'normalized':str(val),'page':docs.index(doc)+1,
                     'document_type':doc,'needs_review':False,'evidence_text':None,'confidence_score':98}
    for key,val in {
        'DOM_NOM_RAISON_SOCIAL_CLIENT':'NOM TEST',
        'DOM_COMPTE_LOCAL':'02700073101107560010',
        'DOM_DATE_DEBUT_CONTRAT':'01/07/2026','DOM_DATE_FIN_CONTRAT':'30/06/2028',
        'DOM_PART_TRANSFERABLE':'350000.00','DOM_MONTANT_TOTAL_DOMICILIE':'8400000.00',
    }.items():f(key,val,docs[0])
    for key,val in {
        'CTR_REFERENCE_DOMICILIATION':'123456|2026|DZD',
        'CTR_NOM_PRENOM_TRAVAILLEUR':'NOM TEST',
        'CTR_DATE_DEBUT_VALIDITE_PERMIS':'01/07/2026',
        'CTR_DATE_FIN_VALIDITE_PERMIS':'30/06/2028',
    }.items():f(key,val,docs[1])
    for key,val in {
        'CTS_NOM_PRENOM_TRAVAILLEUR':'NOM TEST',
        'CTS_PART_TRANSFERABLE':'350000.00','CTS_SALAIRE_NET':'400000.00',
        'CTS_DATE_DEBUT_VALIDITE_PERMIS':'01/07/2026',
        'CTS_DATE_FIN_VALIDITE_PERMIS':'30/06/2028',
    }.items():f(key,val,docs[2])
    for key,val in {
        'TTR_NOM':'NOM','TTR_PRENOM':'TEST',
        'TTR_DATE_DEBUT':'01/07/2026','TTR_DATE_FIN':'30/06/2028',
    }.items():f(key,val,docs[3])
    for key,doc in [(x,docs[1]) for x in ('CTR_SIGNATURE_TRAVAILLEUR_PRESENTE','CTR_SIGNATURE_EMPLOYEUR_PRESENTE','CTR_CACHET_EMPLOYEUR_PRESENT')] + [(x,docs[2]) for x in ('CTS_SIGNATURE_TRAVAILLEUR_PRESENTE','CTS_SIGNATURE_EMPLOYEUR_PRESENTE','CTS_CACHET_EMPLOYEUR_PRESENT')]:
        fields[key]={'raw':'présent','normalized':True,'page':docs.index(doc)+1,'document_type':doc,'needs_review':False,'evidence_text':None,'confidence_score':98}
    return {
        'employeur_id':'EMP_SYNTHETIQUE', 'campagne_id':'DEMO_DOM_2026_01',
        'document_sha256':'a'*64,'pipeline_version':'GENERIC_V15_A_FAST_STANDARDIZED_QWEN3_8_27B',
        'type_dossier':'NOUVEAU_CONTRAT', 'documents':docs,'fields':fields,
        'carthago_dom':{
            'employeur_id':'EMP_SYNTHETIQUE','snapshot_sha256':'b'*64,'record_id':'ROW_001',
            'column_mapping_sha256':mapping_fingerprint(),
            'reference_dom':'123456/2026 DZD','compte_local':'02700073101107560010',
            'montant_total':'8400000.00','nom_complet':'NOM TEST',
            'validation_agence_confirmee':True,'match_cardinality':1
        }
    }

class TestCertification(unittest.TestCase):
    def test_clean_requires_human_certificate(self):
        d=sample(); assessment=validate_dom(d)
        self.assertEqual(assessment['status'],'CONTROLE_OK',assessment['issues'])
        self.assertFalse(assessment['planning_definitif_autorise'])
        cert=certify_dom(d,assessment,'TEST_REVIEWER','Revue humaine fictive')
        self.assertTrue(may_generate_planning(d,cert))

    def test_wrong_ctr_stamp_blocked(self):
        d=sample();d['fields']['CTR_REFERENCE_DOMICILIATION']['raw']='999999/2026 DZD'
        result=validate_dom(d)
        self.assertEqual(result['status'],'BLOQUE')
        self.assertIn('DOM_REFERENCE_MISMATCH',[x['code'] for x in result['issues']])

    def test_bank_ref_missing_blocked(self):
        d=sample();d['carthago_dom']['reference_dom']=''
        self.assertEqual(validate_dom(d)['status'],'BLOQUE')

    def test_ambiguous_bank_rows_blocked(self):
        d=sample();d['carthago_dom']['match_cardinality']=2
        self.assertEqual(validate_dom(d)['status'],'BLOQUE')

    def test_money_mismatch_blocked(self):
        d=sample();d['fields']['CTS_PART_TRANSFERABLE']['raw']='360000.00'
        d['fields']['CTS_PART_TRANSFERABLE']['normalized']='360000.00'
        self.assertIn('DOM_CTS_PART_MISMATCH',[x['code'] for x in validate_dom(d)['issues']])

    def test_permit_dates_mismatch_blocked(self):
        d=sample();d['fields']['TTR_DATE_FIN']['normalized']='30/06/2027'
        self.assertIn('SUPPORTING_DATE_MISMATCH',[x['code'] for x in validate_dom(d)['issues']])

    def test_revision_changes_invalidate_certificate(self):
        d=sample();assessment=validate_dom(d)
        cert=certify_dom(d,assessment,'TEST_REVIEWER','Vérification fictive')
        d['fields']['CTS_SALAIRE_NET']['normalized']='410000.00'
        self.assertFalse(may_generate_planning(d,cert))

    def test_cross_employer_mismatch_blocked(self):
        d=sample();d['carthago_dom']['employeur_id']='AUTRE_ENTREPRISE'
        self.assertIn('EMPLOYER_BANK_SCOPE_MISMATCH',[x['code'] for x in validate_dom(d)['issues']])

    def test_unreadable_stamp_no_inference(self):
        d=sample();d['fields']['CTR_REFERENCE_DOMICILIATION']['raw']=None
        self.assertEqual(validate_dom(d)['status'],'BLOQUE')

    def test_uncertain_dossier_not_certifiable(self):
        d=sample();d['fields']['CTS_PART_TRANSFERABLE']['needs_review']=True
        a=validate_dom(d)
        self.assertEqual(a['status'],'A_VERIFIER')
        with self.assertRaises(ValueError):certify_dom(d,a,'X','Y')

    def test_missing_column_mapping_hash_blocks(self):
        d=sample(); d['carthago_dom'].pop('column_mapping_sha256')
        self.assertIn('BANK_COLUMN_MAPPING_VERSION_MISMATCH', [x['code'] for x in validate_dom(d)['issues']])

    def test_column_mapping_change_invalidates_certificate(self):
        d=sample(); assessment=validate_dom(d)
        cert=certify_dom(d, assessment, 'REVIEWER', 'Revue')
        d['carthago_dom']['column_mapping_sha256']='0'*64
        self.assertFalse(may_generate_planning(d, cert))

    def test_new_amount_precision_not_silently_fixed(self):
        d=sample();d['fields']['CTS_PART_TRANSFERABLE']['normalized']='350000,00'
        self.assertIn('INVALID_FINANCIAL_AMOUNT',[x['code'] for x in validate_dom(d)['issues']])

if __name__=='__main__':unittest.main()
