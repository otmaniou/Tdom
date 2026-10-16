import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from carthagodom_import import extract_horizontal
from carthagodom_mapping import load_mapping, CarthagoMappingError

class TestHorizontalSource(unittest.TestCase):
    def setUp(self):
        self.cfg=load_mapping()
        self.headers=['Client','Nom complet/Raison social','Numéro de domiciliation','Montant initial','Montant final','Total Financing Settlement Amount']
        self.row=['07310109276','PERSONNE TEST','271901202624000056DZD','23054064.12','23054064.12','9603005.55']
    def test_exact_headers_and_two_rows(self):
        out=extract_horizontal(self.headers,[self.row,self.row],self.cfg,employeur_id='TOSYALI')
        self.assertEqual(out['nb_lignes'],2)
        self.assertEqual(out['lignes'][0]['champs']['reference_dom'],'271901202624000056DZD')
        self.assertEqual(out['lignes'][0]['champs_complementaires']['total_financing_settlement_amount'],'9603005.55')
        self.assertFalse(out['lignes'][0]['certification_autorisee'])
    def test_wrong_label_fails_without_alias(self):
        headers=self.headers.copy(); headers[1]='Nom complet/Raison sociale'
        with self.assertRaisesRegex(CarthagoMappingError,'COLONNES_ABSENTES'):
            extract_horizontal(headers,[self.row],self.cfg,employeur_id='TOSYALI')
    def test_duplicate_headers_blocked(self):
        headers=self.headers+['Client']
        with self.assertRaisesRegex(CarthagoMappingError,'COLONNES_DUPLIQUEES'):
            extract_horizontal(headers,[self.row+['x']],self.cfg,employeur_id='TOSYALI')
    def test_change_label_once(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['colonnes']['nom_complet']='Autre libellé exact'
        headers=self.headers.copy();headers[1]='Autre libellé exact'
        out=extract_horizontal(headers,[self.row],cfg,employeur_id='TOSYALI')
        self.assertEqual(out['lignes'][0]['champs']['nom_complet'],'PERSONNE TEST')
    def test_missing_value_flagged(self):
        row=self.row.copy();row[2]=None
        out=extract_horizontal(self.headers,[row],self.cfg,employeur_id='TOSYALI')
        self.assertIn('VALEUR_OBLIGATOIRE_ABSENTE:reference_dom',out['lignes'][0]['anomalies_import'])
    def test_numeric_client_is_not_silently_converted(self):
        row=self.row.copy();row[0]=7310109276
        out=extract_horizontal(self.headers,[row],self.cfg,employeur_id='TOSYALI')
        self.assertIn('IDENTIFIANT_EXCEL_NUMERIQUE_A_VERIFIER:client_code',out['lignes'][0]['anomalies_import'])
    def test_blank_rows_skipped_and_counted(self):
        out=extract_horizontal(self.headers,[[None]*len(self.headers),self.row],self.cfg,employeur_id='TOSYALI')
        self.assertEqual(out['lignes_vides_ignorees'],1)
        self.assertEqual(out['lignes'][0]['excel_row'],3)
    def test_employer_required(self):
        with self.assertRaisesRegex(CarthagoMappingError,'EMPLOYEUR_OBLIGATOIRE'):
            extract_horizontal(self.headers,[self.row],self.cfg)

if __name__=='__main__':unittest.main()
