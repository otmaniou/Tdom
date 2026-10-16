import unittest, tempfile, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rapprochement_v08 import account_to_id,pdf_account,resolve_header,load_predom,run
class TestV09(unittest.TestCase):
 def test_client_id(self):
  self.assertEqual(account_to_id('02700731011166100117'),'07310111661')
 def test_pdf(self):
  self.assertEqual(pdf_account('02700731011166100117-202608-AUG_AKGUN_CANER_CAN.pdf'),'02700731011166100117')
 def test_header(self):
  self.assertEqual(resolve_header(['Request\xa0 Decision  Date'],'Request Decision Date'),'Request\xa0 Decision  Date')
 def test_integration(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'data/pdf').mkdir(parents=True);(p/'data/json/.ipynb_checkpoints').mkdir(parents=True)
   stem='02700731011166100117-202608-AUG_TEST'
   (p/'data/pdf'/(stem+'.pdf')).write_bytes(b'%PDF-1.4')
   (p/'data/json'/(stem+'.json')).write_text(json.dumps({'DOM_COMPTE_LOCAL':'02700731011166100117','CTS_NOM_PRENOM_TRAVAILLEUR':'TEST ALI'}))
   (p/'data/json/.ipynb_checkpoints'/(stem+'-checkpoint.json')).write_text('{}')
   (p/'data/predom.csv').write_text('Client;Référence;Statut;Nom complet/Raison social;Request Decision Date\n07310111661;P-OLD;Domicilié;TEST ALI;01/01/2025\n07310111661;P-NEW;Accord Prédom;TEST ALI;12/10/2026\n',encoding='utf8')
   cfg={'header_row':1,'sheet_name':None,'colonnes':{'client_id':'Client','predom_reference':'Référence','status':'Statut','name':'Nom complet/Raison social','decision_date':None},'statuts_eligibles':['Accord Prédom','Domicilié'],'seuil_nom_a_verifier':85}
   (p/'cfg.json').write_text(json.dumps(cfg))
   r=run(p,p/'data/predom.csv',p/'cfg.json')
   self.assertEqual(r[0]['reference_predom_candidate'],'P-NEW')
   self.assertEqual(r[0]['client_id'],'07310111661')
   self.assertEqual(r[0]['reference_dom'],'')
   self.assertEqual(r[0]['validation'],'NON_EFFECTUEE')
   summary=json.loads((p/'resultats/rapport_rapprochement_v08.json').read_text())
   self.assertEqual(summary['nb_json'],1)
   self.assertTrue(summary['date_decision_disponible'])
 def test_ambiguity(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'data/pdf').mkdir(parents=True);(p/'data/json').mkdir(parents=True)
   stem='02700731011166100117-202608-AUG_TEST'
   (p/'data/pdf'/(stem+'.pdf')).write_bytes(b'%PDF')
   (p/'data/json'/(stem+'.json')).write_text(json.dumps({'DOM_COMPTE_LOCAL':'02700731011166100117','CTS_NOM_PRENOM_TRAVAILLEUR':'TEST ALI'}))
   (p/'data/predom.csv').write_text('Client;Référence;Statut;Nom complet/Raison social;Request Decision Date\n07310111661;P-A;Accord Prédom;TEST ALI;12/10/2026\n07310111661;P-B;Accord Prédom;TEST ALI;12/10/2026\n',encoding='utf8')
   cfg={'colonnes':{'client_id':'Client','predom_reference':'Référence','status':'Statut','name':'Nom complet/Raison social','decision_date':'Request Decision Date'},'statuts_eligibles':['Accord Prédom'],'seuil_nom_a_verifier':85}
   (p/'cfg.json').write_text(json.dumps(cfg))
   r=run(p,p/'data/predom.csv',p/'cfg.json')
   self.assertEqual(r[0]['reference_predom_candidate'],'')
   self.assertIn('AMBIGUITE_DERNIERE_DECISION',r[0]['anomalies'])
if __name__=='__main__':unittest.main()
