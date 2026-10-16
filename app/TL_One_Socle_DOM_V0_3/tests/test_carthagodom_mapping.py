import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from carthagodom_mapping import (load_mapping, check_headers, check_configuration_ready,
                                  map_bank_row, mapping_fingerprint, CarthagoMappingError)


def mapping_complete():
    m = copy.deepcopy(load_mapping())
    m['colonnes'].update({
        'reference_dom': 'REF DOM DE TEST',
        'compte_local': 'COMPTE DE TEST',
        'montant_total': 'MONTANT DE TEST',
        'statut_domiciliation': 'STATUT DE TEST',
    })
    m['valeurs_statut_valide'] = ['VALIDEE_TEST']
    return m

class TestStrictMapping(unittest.TestCase):
    def test_known_columns_exact(self):
        m=load_mapping()
        self.assertEqual(m['colonnes']['client_code'], 'Client')
        self.assertEqual(m['colonnes']['nom_complet'], 'Nom complet/Raison social')
    def test_placeholder_prevents_processing(self):
        with self.assertRaisesRegex(CarthagoMappingError,'LIBELLES_NON_CONFIGURES'):
            check_configuration_ready(load_mapping())
    def test_header_alias_is_not_used(self):
        m=mapping_complete()
        headers=['CLIENT','Nom complet/Raison social','REF DOM DE TEST','COMPTE DE TEST','MONTANT DE TEST','STATUT DE TEST']
        with self.assertRaisesRegex(CarthagoMappingError, "client_code attendu exactement 'Client'"):
            check_headers(headers,m)
    def test_accent_or_space_difference_fails(self):
        m=mapping_complete()
        headers=['Client','Nom complet /Raison sociale','REF DOM DE TEST','COMPTE DE TEST','MONTANT DE TEST','STATUT DE TEST']
        with self.assertRaisesRegex(CarthagoMappingError,'COLONNES_ABSENTES'):
            check_headers(headers,m)
    def test_rename_once_in_mapping_works(self):
        m=mapping_complete()
        m['colonnes']['client_code'] = 'Identifiant client (nouvelle version)'
        headers=list(m['colonnes'].values())
        self.assertEqual(check_headers(headers,m)['mode'],'STRICT_EXACT_ONLY')
    def test_duplicate_headers_fails(self):
        m=mapping_complete()
        headers=list(m['colonnes'].values()) + ['Client']
        with self.assertRaisesRegex(CarthagoMappingError,'COLONNES_DUPLIQUEES'):
            check_headers(headers,m)
    def test_ambiguous_mapping_fails(self):
        m=mapping_complete(); m['colonnes']['compte_local']='Client'
        with self.assertRaisesRegex(CarthagoMappingError,'CONFIG_INVALIDE'):
            # validation normally performed by load_mapping; check this case using temp file
            import tempfile, json
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'mapping.json'
                p.write_text(json.dumps(m),encoding='utf-8')
                load_mapping(p)
    def test_bank_row_never_approves_unknown_status(self):
        m=mapping_complete()
        row={x:'test' for x in m['colonnes'].values()}
        row['STATUT DE TEST']='NON_VALIDE'
        result=map_bank_row(row,m,employeur_id='EMP_TEST',snapshot_sha256='a'*64,record_id='R1',match_cardinality=1,mapping_sha256='b'*64)
        self.assertIs(result['validation_agence_confirmee'],False)
        row['STATUT DE TEST']='VALIDEE_TEST'
        self.assertIs(map_bank_row(row,m,employeur_id='EMP_TEST',snapshot_sha256='a'*64,record_id='R1',match_cardinality=1,mapping_sha256='b'*64)['validation_agence_confirmee'],True)
    def test_no_status_whitelist_is_blocking(self):
        m=mapping_complete();m['valeurs_statut_valide']=[]
        with self.assertRaisesRegex(CarthagoMappingError,'STATUT_VALIDE_NON_CONFIGURE'):
            check_configuration_ready(m)
    def test_empty_required_value_blocked(self):
        m=mapping_complete();row={x:'test' for x in m['colonnes'].values()}
        row['COMPTE DE TEST']=''
        with self.assertRaisesRegex(CarthagoMappingError,'VALEURS_BANCAIRES_VIDES'):
            map_bank_row(row,m,employeur_id='E',snapshot_sha256='a'*64,record_id='R1',match_cardinality=1,mapping_sha256='b'*64)
    def test_config_hash_stable(self):
        self.assertEqual(len(mapping_fingerprint()),64)

if __name__ == '__main__':
    unittest.main()
