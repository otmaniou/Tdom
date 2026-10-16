import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tl_one_v10 as v

ROOT = Path(__file__).resolve().parents[1]


def example_raw(engine,docname='02700731011166100117-202608-TEST.pdf',wrong_ctr=False):
    recs=[]
    docs=[('CONTRAT_SPECIFIQUE',{'CTS_NOM_PRENOM_TRAVAILLEUR':'TEST EXEMPLE','CTS_SALAIRE_NET':'450.000,00','CTS_DATE_DEBUT_CONTRAT':'01/06/2026','CTS_PART_TRANSFERABLE':'230.000,00'}),
          ('CONTRAT_TRAVAIL',{'CTR_NOM_PRENOM_TRAVAILLEUR':'EXEMPLE TEST','CTR_SALAIRE_NET':'445.000,00' if wrong_ctr else '450.000,00','CTR_DATE_DEBUT_CONTRAT':'01/06/2026'}),
          ('ENGAGEMENT_DOMICILIATION',{'DOM_NOM_RAISON_SOCIAL_CLIENT':'TEST EXEMPLE','DOM_SALAIRE_NET_MENSUEL':'450.000,00','DOM_DATE_DEBUT_CONTRAT':'01/06/2026','DOM_COMPTE_LOCAL':'02700731011166100117'}),
          ('TITRE_TRAVAIL',{'TTR_NOM':'TEST','TTR_PRENOM':'EXEMPLE','TTR_DATE_DEBUT':'01/06/2026'})]
    for i,(doc,fields) in enumerate(docs,1):
        fc={k:{'score':95,'basis':'FICTIF_TEST'} for k in fields}
        recs.append({'doc_type':doc,'page_num':i,'raw_data':fields,'field_confidence':fc,
           'extraction_confidence_score':96, 'extraction_status':'OK', 'extraction_confidence_band':'HIGH',
           'quality_flags':[],'field_revisions':[],'field_disagreements':[]})
    return {'schema_version':engine['SCHEMA_VERSION'],'field_schema_hash':engine['EXPECTED_FIELD_SCHEMA_HASH'],
        'pipeline_version':engine['EXPECTED_SOURCE_PIPELINE_VERSION'],'source_file':docname,'page_records':recs}


class V10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e=v.load_engine()

    def test_schema_engine_and_native_normalization(self):
        self.assertEqual(len(self.e['ALL_FIELDS']),99)
        a=self.e['normalize_field_trace']('CTS_SALAIRE_NET','450.000,00')
        self.assertEqual(float(a['normalized']),450000.0)

    def test_native_part2_and_cts_mismatch(self):
        raw=example_raw(self.e,wrong_ctr=True)
        out=self.e['process_raw_dossier'](raw)
        self.assertEqual(len(out),8)
        mapping=v.corrected_mapping()
        self.assertEqual(mapping['champs_metier']['client_identifiant']['sources']['PREDOM'],['Client'])
        rec={'reference_predom_candidate':'PR-10','client_id':'07310111661','nom_predom':'TEST EXEMPLE','statut_predom':'Accord Prédom','reference_dom':''}
        rows,mis=v.evaluate_line(out[0],rec,self.e,mapping['champs_metier'])
        by={x['champ_metier']:x for x in rows}
        self.assertEqual(by['salaire_net']['comparaison']['CTR'],'ECART')
        self.assertEqual(by['client_nom']['comparaison']['CTR'],'CONFORME')
        self.assertEqual(by['predom_reference']['cellules']['Prédom']['valeur'],'PR-10')
        self.assertEqual(by['predom_reference']['comparaison']['Prédom'],'REFERENCE')
        self.assertIsNone(by['reference_dom_officielle']['cellules']['Prédom']['valeur'])
        self.assertTrue(any(m['champ_metier']=='salaire_net' for m in mis))
        self.assertEqual(by['client_nom']['cellules']['CTS']['score_extraction'],95)
        self.assertIsNotNone(by['salaire_net']['cellules']['CTS']['score_qualite'])

    def test_avoid_fake_ttr_fields(self):
        raw=example_raw(self.e)
        processed=self.e['process_raw_dossier'](raw)[0]
        c=v.build_cell(processed,self.e,'TTR',['TTR_POSTE'],{},'poste')
        self.assertEqual(c['etat'],'NON_EXTRAIT_VOLONTAIREMENT')

    def test_end_to_end_and_preserves_v09(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'data/json').mkdir(parents=True);(root/'resultats').mkdir()
            raw=example_raw(self.e,wrong_ctr=True)
            pdf='data/pdf/'+raw['source_file']
            jp='data/json/'+raw['source_file'].replace('.pdf','.json')
            (root/jp).write_text(json.dumps(raw),encoding='utf8')
            with (root/'resultats/rapprochement_v08.csv').open('w',newline='',encoding='utf8') as f:
                w=csv.DictWriter(f,fieldnames=['pdf','json','client_id','reference_predom_candidate','selection','nom_predom','statut_predom','date_decision','reference_dom','anomalies'],delimiter=';')
                w.writeheader();w.writerow({'pdf':pdf,'json':jp,'client_id':'07310111661','reference_predom_candidate':'PR-10','selection':'CANDIDAT_A_VERIFIER','nom_predom':'TEST EXEMPLE','statut_predom':'Accord Prédom','date_decision':'2026-10-01','reference_dom':'','anomalies':''})
            before=(root/'resultats/rapprochement_v08.csv').read_bytes()
            with contextlib_redirect():
                result=v.process(root)
            self.assertFalse(result['erreurs'],result['erreurs'])
            self.assertTrue(result['ecarts'])
            self.assertEqual((root/'resultats/rapprochement_v08.csv').read_bytes(),before)
            details=json.loads((root/'resultats/v10/comparatif_dossiers_v10.json').read_text())
            self.assertEqual(len(details['dossiers']),1)
            self.assertEqual(details['dossiers'][0]['validation_agence'],'NON_EFFECTUEE')

    def test_protect_bad_json_and_path(self):
        with self.assertRaises(ValueError):v.under_root(Path('/tmp/foo'),'../../etc/passwd')
        self.assertFalse(v.equivalent('99','100','amount'))


class contextlib_redirect:
    def __enter__(self):
        import contextlib,io
        self.cm=contextlib.redirect_stdout(io.StringIO());self.cm.__enter__()
    def __exit__(self,*args):return self.cm.__exit__(*args)

if __name__=='__main__':unittest.main()
