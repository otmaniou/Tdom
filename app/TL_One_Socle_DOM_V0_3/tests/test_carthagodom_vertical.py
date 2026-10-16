import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from carthagodom_mapping import load_mapping, CarthagoMappingError
from carthagodom_vertical import extract_vertical

class TestVerticalSource(unittest.TestCase):
    def setUp(self): self.cfg=load_mapping()
    def test_exact_extraction(self):
        x=extract_vertical([('domiciliation',''), ('Client','07310109276'), ('Nom complet/Raison social','PERSONNE TEST'),('Numéro de domiciliation','271901202624000056DZD'),('Montant initial','23054064.12'),('Montant final','23054064.12'),('Total Financing Settlement Amount','9603005.55')],self.cfg)
        self.assertEqual(x['donnees_preliminaires']['reference_dom'],'271901202624000056DZD')
        self.assertEqual(x['montants_distincts']['Total Financing Settlement Amount'],'9603005.55')
        self.assertIsNone(x['donnees_preliminaires']['compte_local'])
        self.assertFalse(x['certification_autorisee'])
    def test_wrong_label_blocks(self):
        with self.assertRaisesRegex(CarthagoMappingError,'LIBELLES_OU_VALEURS_ABSENTS'):
            extract_vertical([('Client','001'),('Nom complet/Raison sociale','TEST'),('Numéro de domiciliation','001DZD'),('Montant final','123.45')], self.cfg)
    def test_single_change_controls_expected_label(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['colonnes']['nom_complet']='Nouveau Libelle Unique'
        p=extract_vertical([('Client','001'),('Nouveau Libelle Unique','TEST'),('Numéro de domiciliation','001DZD'),('Montant final','123.45')],cfg)
        self.assertEqual(p['donnees_preliminaires']['nom_complet'],'TEST')
    def test_duplicate_blocks(self):
        with self.assertRaisesRegex(CarthagoMappingError,'LIBELLE_EN_DOUBLE'):
            extract_vertical([('Client','1'),('Client','2')],self.cfg)
if __name__=='__main__':unittest.main()
