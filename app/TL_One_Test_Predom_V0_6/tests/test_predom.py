import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from predom_pilot import analyze,_date,_status
CFG={'colonnes':{'client_id':'Identifiant client','dom_reference':'Numéro de domiciliation','status':'Statut','decision_date':'Request Decision Date'},'statuts_eligibles':['Domicilié','Accord Prédom']}
HEADERS=list(CFG['colonnes'].values())
class PredomTests(unittest.TestCase):
    def calc(self,rows):return analyze(HEADERS,[(i+2,r) for i,r in enumerate(rows)],CFG)
    def test_latest_eligible(self):
        x=self.calc([['0001','DOM-A','Domicilié','01/01/2025'],['0001','DOM-B','Accord Prédom','11/10/2026']])
        self.assertEqual(x['dossiers'][0]['reference_proposee'],'DOM-B')
        self.assertEqual(x['historique_predom'][0]['selection'],'NON_RETENUE')
    def test_reject_latest_noneligible(self):
        x=self.calc([['0001','DOM-A','Domicilié','01/01/2025'],['0001','DOM-B','Rejeté','11/10/2026']])
        self.assertEqual(x['dossiers'][0]['reference_proposee'],'DOM-A')
    def test_ambiguity_same_date(self):
        x=self.calc([['0001','DOM-A','Domicilié','11/10/2026'],['0001','DOM-B','Accord Prédom','11/10/2026']])
        self.assertEqual(x['dossiers'][0]['statut_selection'],'AMBIGUITE_MEME_DATE')
    def test_invalid_date_no_auto_selection(self):
        x=self.calc([['0001','DOM-A','Domicilié','date inconnue']])
        self.assertEqual(x['dossiers'][0]['statut_selection'],'AUCUNE_CANDIDATE_ELIGIBLE')
    def test_missing_client_does_not_group(self):
        x=self.calc([['','DOM-A','Domicilié','01/01/2025']])
        self.assertEqual(x['nb_clients'],0)
    def test_numeric_client_rejected(self):
        x=self.calc([[7310109,'DOM-A','Domicilié','01/01/2025']])
        self.assertEqual(x['dossiers'][0]['statut_selection'],'AUCUNE_CANDIDATE_ELIGIBLE')
    def test_no_ca10_no_certification(self):
        x=self.calc([['0001','DOM-A','Domicilié','01/01/2025']])
        self.assertEqual(x['dossiers'][0]['ca10'],'ABSENT_NON_VERIFIE')
        self.assertEqual(x['dossiers'][0]['validation_dossier'],'NON_EFFECTUEE')
    def test_exact_headers(self):
        with self.assertRaisesRegex(ValueError,'Colonnes exactes absentes'):
            analyze(['identifiant client','Numéro de domiciliation','Statut','Request Decision Date'],[],CFG)
    def test_parse_date(self):
        self.assertEqual(_date('2026-10-12').strftime('%Y-%m-%d'),'2026-10-12')
        self.assertIsNone(_date(46110))
if __name__=='__main__': unittest.main()
