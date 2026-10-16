import sys,unittest,tempfile,json,csv
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rapprochement_v08 import account_to_id,pdf_account,name_score,recursive_fields,run
class TestRapprochement(unittest.TestCase):
 def test_cle(self):self.assertEqual(account_to_id('02700731011153400101'),'07310111534')
 def test_nom_pdf(self):self.assertEqual(pdf_account('02700731011153400101-202610-dom-TEST.pdf'),'02700731011153400101')
 def test_mauvais_pdf(self):self.assertIsNone(pdf_account('02700731011153400101-202613-dom-TEST.pdf'))
 def test_inversion(self):self.assertEqual(name_score('YILDIRIM IBRAHIM','IBRAHIM YILDIRIM'),100)
 def test_json(self):self.assertEqual(recursive_fields({'x':{'CTS_NOM_PRENOM_TRAVAILLEUR':'ALI TEST'}},{'CTS_NOM_PRENOM_TRAVAILLEUR'})[0][1],'ALI TEST')
 def test_integration_sans_date(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'data/pdf').mkdir(parents=True);(p/'data/json').mkdir(parents=True)
   stem='02700731011153400101-202610-dom-TEST'
   (p/'data/pdf'/(stem+'.pdf')).write_bytes(b'%PDF-1.4')
   (p/'data/json'/(stem+'.json')).write_text(json.dumps({'DOM_COMPTE_LOCAL':'02700731011153400101','CTS_NOM_PRENOM_TRAVAILLEUR':'TEST ALI'}))
   (p/'data/predom.csv').write_text('Client;Référence;Statut;Nom complet/Raison social\n07310111534;P-123;Accord Prédom;ALI TEST\n',encoding='utf8')
   cfg={'header_row':1,'sheet_name':None,'colonnes':{'client_id':'Client','predom_reference':'Référence','status':'Statut','name':'Nom complet/Raison social','decision_date':None},'statuts_eligibles':['Accord Prédom'],'seuil_nom_a_verifier':85}
   (p/'cfg.json').write_text(json.dumps(cfg))
   result=run(p,p/'data/predom.csv',p/'cfg.json')
   self.assertEqual(result[0]['client_id'],'07310111534')
   self.assertEqual(result[0]['meilleur_score_nom_parmi_eligibles'],100)
   self.assertEqual(result[0]['reference_predom_candidate'],'')
   self.assertIn('SELECTION_INTERDITE',result[0]['anomalies'])
if __name__=='__main__':unittest.main()
