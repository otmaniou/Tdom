"""TL-One V1.0 — moteur de comparaison: réutilise le calcul exact de Partie 2 V15-A.

Lecture seule; aucune validation bancaire, aucune modification de V0.9/RAW.
"""
from __future__ import annotations
import argparse
import contextlib
import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
PART2_HASH = 'd7fc8e7485a83c69f5ed7160f01807e77adc8f903ec8e15579385f1170c0328e'
LOADER_CELLS = (4, 6, 7, 9, 11, 13, 14, 18, 22, 24, 25)
DOC_TYPES = {'CTS':'CONTRAT_SPECIFIQUE','CTR':'CONTRAT_TRAVAIL','DOM':'ENGAGEMENT_DOMICILIATION','TTR':'TITRE_TRAVAIL'}
ORDER = ('CTS','DOM','CTR','TTR','Prédom')


def load_engine(path=None):
    """Charger uniquement la logique et les fonctions V15-A, jamais sa cellule batch.

    La cellule 18 contient des ASSERT de démonstration utilisant ACCOUNT_EXAMPLE
    (placeholder invalide). On ignore uniquement cette fin de cellule; les
    fonctions réelles et leurs règles ne sont pas modifiées.
    """
    path = Path(path or BASE/'vendor/part2_v15_A.ipynb')
    if hashlib.sha256(path.read_bytes()).hexdigest() != PART2_HASH:
        raise RuntimeError('Notebook Partie 2 différent de la version vérifiée : interrompu, aucune substitution silencieuse.')
    book = json.loads(path.read_text(encoding='utf-8'))
    env = {'__name__': 'tl_one_v15a_engine'}
    with contextlib.redirect_stdout(io.StringIO()):
        for idx in LOADER_CELLS:
            code=''.join(book['cells'][idx]['source'])
            if idx == 18:
                if '# Tests V5.3 demandés.' not in code:
                    raise RuntimeError('Ancre de protection absente dans la Partie 2')
                code = code.split('# Tests V5.3 demandés.')[0]
            exec(compile(code, f'V15A_PART2_CELL_{idx}', 'exec'),env)
    if len(env['ALL_FIELDS'])!=99: raise RuntimeError('Schéma inattendu')
    return env


def present(v): return v is not None and v!='' and v!=[]

def text(v):
    if v is None:return ''
    if isinstance(v,float) and v.is_integer(): return str(int(v))
    return str(v).strip()


def norm_text(s):
    s=unicodedata.normalize('NFKD', text(s)).upper()
    s=''.join(ch for ch in s if not unicodedata.combining(ch))
    return ' '.join(re.findall(r'\w+',s))


def equivalent(a,b,kind,field=''):
    if not present(a) or not present(b): return None
    if kind == 'amount':
        try:
            from decimal import Decimal
            return abs(Decimal(str(a))-Decimal(str(b)))<=Decimal('0.01')
        except Exception:return None
    if kind in {'date','integer','percentage','boolean','reference'}:
        return text(a).upper()==text(b).upper()
    if field=='client_nom':
        aa,bb=norm_text(a).split(),norm_text(b).split()
        return bool(aa and bb) and sorted(aa)==sorted(bb)
    return norm_text(a)==norm_text(b)


def get_selected_rec(records,doc,field_names):
    """Ne pas choisir silencieusement une version de contrat parmi des valeurs divergentes."""
    candidates=[]
    for rec in records:
        if rec.get('doc_type')!=DOC_TYPES[doc]:continue
        vals=rec.get('normalized_data') or {}
        for key in field_names:
            if present(vals.get(key)):
                candidates.append((rec,key,vals[key]))
    if not candidates:return None,False
    unique={text(v) for _,_,v in candidates}
    if len(unique)>1:return candidates,True
    return candidates,False


def primitive(value):
    if isinstance(value,(str,int,float,bool)) or value is None:return value
    return str(value)


def build_cell(processed,engine,doc,source_fields,meta,field_id):
    matching,ambiguous=get_selected_rec(processed.get('page_records') or [],doc,source_fields)
    if not matching:
        doc_present=any(x.get('doc_type')==DOC_TYPES[doc] and not x.get('is_virtual_subdocument') for x in processed.get('page_records') or [])
        ttr_inactive=(doc=='TTR' and bool(source_fields) and all(f in engine['TTR7_INACTIVE_FIELDS'] for f in source_fields))
        return {'etat':'NON_EXTRAIT_VOLONTAIREMENT' if ttr_inactive else 'CHAMP_ABSENT' if doc_present else 'DOCUMENT_ABSENT','valeur':None,'brut':None,'champs_sources':source_fields,'score_extraction':None,'score_qualite':None,'page':None,'detail':None}
    if ambiguous:
        return {'etat':'VERSIONS_DIVERGENTES','valeur':None,'brut':[primitive(t[0].get('raw_data',{}).get(t[1])) for t in matching], 'champs_sources':source_fields,'score_extraction':None,'score_qualite':None,'page':[t[0].get('page_num') for t in matching],'detail':'Plusieurs valeurs différentes dans le même document : examen humain requis'}
    rec,key,val=matching[0]
    fc=(rec.get('field_confidence') or {}).get(key) or {}
    p2=(meta.get(key) or {})
    trace=(rec.get('normalization_trace') or {}).get(key) or {}
    return {'etat':'EXTRAIT','valeur':primitive(val),'brut':primitive((rec.get('raw_data') or {}).get(key)),
      'champs_sources':[key], 'score_extraction':fc.get('score'), 'raison_extraction':fc.get('basis'),
      'score_page':rec.get('extraction_confidence_score'),'score_qualite':p2.get('FIELD_CONFIDENCE'),
      'raison_qualite':p2.get('FIELD_CONFIDENCE_REASON'),'importance_dq':p2.get('DQ_IMPORTANCE'),
      'page':rec.get('page_num'),'etat_extraction':rec.get('extraction_status'),
      'statut_normalisation':trace.get('status'),'regle_normalisation':trace.get('rule'),
      'message_normalisation':trace.get('message'), 'source_document':rec.get('doc_type'),
      'indicateur_non_probabiliste':True}


def ttr_name(processed,engine,meta):
    a=build_cell(processed,engine,'TTR',['TTR_NOM'],meta,'client_nom')
    b=build_cell(processed,engine,'TTR',['TTR_PRENOM'],meta,'client_nom')
    if a['etat']=='EXTRAIT' and b['etat']=='EXTRAIT':
        a['valeur']=text(a['valeur'])+' '+text(b['valeur'])
        a['brut']=text(a['brut'])+' '+text(b['brut'])
        a['champs_sources']=['TTR_NOM','TTR_PRENOM']
        sc=[x for x in (a.get('score_extraction'),b.get('score_extraction')) if isinstance(x,(int,float))]
        a['score_extraction']=min(sc) if sc else None
        dq=[x for x in (a.get('score_qualite'),b.get('score_qualite')) if isinstance(x,(int,float))]
        a['score_qualite']=min(dq) if dq else None
        return a
    return a if a['etat']!='EXTRAIT' else b


def predom_cells(row):
    """Uniquement les colonnes effectivement transmises par le rapport V0.9."""
    def make(value,source):
        return {'etat':'EXCEL_PREDOM' if present(value) else 'NON_DISPONIBLE_V09',
          'valeur':value if present(value) else None,'brut':value if present(value) else None,
          'champs_sources':[source], 'score_extraction':None,'score_qualite':None,'page':None,
          'detail':'Provenance : sélection candidate du rapprochement V0.9. Pas de score OCR Excel.'}
    return {
        'client_nom':make(row.get('nom_predom'), 'Nom complet/Raison social'),
        'client_identifiant':make(row.get('client_id'),'Client'),
        'predom_reference':make(row.get('reference_predom_candidate'),'Référence'),
        'predom_statut':make(row.get('statut_predom'),'Statut'),
        # Le numéro DOM n'est jamais déduit de la référence Prédom.
        'reference_dom_officielle':make(row.get('reference_dom'),'Référence DOM confirmée'),
    }


def corrected_mapping(path=None):
    raw=json.loads(Path(path or BASE/'config/champs_metier_base_v05.json').read_text(encoding='utf8'))
    # Corrections V1.0 : distinct Prédom/DOM, en-tête réel 'Client'.
    raw['champs_metier']['client_identifiant']['sources']['PREDOM']=['Client']
    raw['champs_metier']['reference_dom_officielle']['sources']['PREDOM']=[]
    raw['champs_metier']['reference_dom_officielle']['reference']='CARTHAGODOM_CONFIRME'
    return raw


def evaluate_line(processed,v09row,engine,fields):
    by_conf={x.get('CHAMP'):x for x in (processed.get('field_confidence') or [])}
    predom=predom_cells(v09row)
    rows=[];issues=[]
    for key,desc in fields.items():
        ref=desc.get('reference');sources=desc.get('sources') or {}
        cells={}
        for doc in ORDER:
            keys=sources.get('PREDOM' if doc=='Prédom' else doc) or []
            if doc=='Prédom':
                if keys or key=='reference_dom_officielle': cells[doc]=predom.get(key) or {'etat':'NON_DISPONIBLE_V09','valeur':None,'brut':None}
                else:cells[doc]={'etat':'NON_DISPONIBLE_V09','valeur':None,'brut':None}
            elif not keys:
                cells[doc]={'etat':'NON_APPLICABLE','valeur':None,'brut':None}
            elif doc=='TTR' and key=='client_nom':
                cells[doc]=ttr_name(processed,engine,by_conf)
            else:cells[doc]=build_cell(processed,engine,doc,keys,by_conf,key)
        baseline='Prédom' if ref=='PREDOM' else (ref if ref in cells else None)
        if ref in {'CTS_DERIVED','CA10','CARTHAGODOM_CONFIRME'}:baseline=None
        ref_value=(cells.get(baseline) or {}).get('valeur')
        statuses={}
        for doc in ORDER:
            cell=cells[doc]
            if cell['etat'] in ('NON_APPLICABLE','NON_EXTRAIT_VOLONTAIREMENT'):
                statuses[doc]=cell['etat'];continue
            if cell['etat']=='VERSIONS_DIVERGENTES':statuses[doc]='ANOMALIE_VERSIONS';continue
            if not present(cell.get('valeur')):
                statuses[doc]=cell['etat'];continue
            if baseline==doc:statuses[doc]='REFERENCE';continue
            if baseline and not present(ref_value):statuses[doc]='REFERENCE_ABSENTE';continue
            if baseline:
                equal=equivalent(cell.get('valeur'),ref_value,desc.get('type'),key)
                statuses[doc]='CONFORME' if equal is True else 'ECART' if equal is False else 'INCOMPARABLE'
                if equal is False:
                    issues.append({'champ_metier':key,'source':doc,'reference':baseline,'valeur_source':cell.get('valeur'),'valeur_reference':ref_value,'code':'ECART_REFERENCE_CTS' if baseline=='CTS' else 'ECART_REFERENCE'})
            else:statuses[doc]='INFORMATIF_SANS_COMPARAISON'
        rows.append({'champ_metier':key,'libelle':desc.get('libelle',key),'groupe':desc.get('groupe'),
                     'type':desc.get('type'),'reference':ref,'importance':desc.get('importance'),
                     'cellules':cells,'comparaison':statuses,
                     'note':desc.get('note')})
    return rows,issues


def load_v09(path):
    p=Path(path)
    if not p.exists():raise FileNotFoundError('Rapport V0.9 absent : '+str(p))
    with p.open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f,delimiter=';'))
    if not rows:raise ValueError('Rapport V0.9 vide')
    mandatory={'pdf','json','client_id','reference_predom_candidate','selection'}
    if not mandatory.issubset(rows[0]):raise ValueError('En-têtes V0.9 non conformes')
    return rows


def under_root(root,relative):
    if not relative:return None
    p=(root/relative).resolve()
    if not p.is_relative_to(root.resolve()):raise ValueError('Chemin hors projet: '+relative)
    return p


def save_csv(path,rows,columns):
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=columns,delimiter=';',extrasaction='ignore')
        w.writeheader();w.writerows(rows)


def process(root, v09path=None, part2path=None, mappingpath=None):
    root=Path(root).resolve()
    rows09=load_v09(v09path or root/'resultats/rapprochement_v08.csv')
    engine=load_engine(part2path)
    mapping=corrected_mapping(mappingpath)
    target=root/'resultats/v10';target.mkdir(parents=True,exist_ok=True)
    output=[];summary=[];longrows=[];issues=[];errors=[];detail=[]
    for ix,v09 in enumerate(rows09,1):
        dossier={'index':ix,'pdf':v09.get('pdf'),'json':v09.get('json'), 'client_id':v09.get('client_id'),
                 'reference_predom_candidate':v09.get('reference_predom_candidate'),
                 'reference_dom':v09.get('reference_dom') or None,'statut_predom':v09.get('statut_predom'),
                 'date_decision':v09.get('date_decision'),'selection_v09':v09.get('selection'),
                 'anomalies_v09':v09.get('anomalies'),'ca10':'ABSENT_NON_VERIFIE','cachet_dom':'SUSPENDU',
                 'validation_agence':'NON_EFFECTUEE','lignes':[],'anomalies_v15a':[]}
        file_path=None
        try:
            file_path=under_root(root,v09.get('json'))
            if file_path is None or not file_path.is_file():raise ValueError('JSON_V15A_ABSENT')
            obj=json.loads(file_path.read_text(encoding='utf-8-sig'))
            if not engine['validate_raw_contract'](obj):raise ValueError('JSON_V15A_SCHEMA_INCOMPATIBLE')
            source_name=Path(v09.get('pdf') or '').name
            if obj.get('source_file') and Path(obj['source_file']).name.casefold()!=source_name.casefold():
                raise ValueError('JSON_SOURCE_FILE_DIFFERENT_DU_PDF')
            processed,field_rows,anomalies,retry,confidence,dq,manual,cross=engine['process_raw_dossier'](obj)
            dossier['moteur_v15a']='PARTIE_2_V15_A_OFFICIELLE'
            dossier['dq_summary']=dq
            dossier['anomalies_v15a']=anomalies
            dossier['retry_requests']=retry
            mr,mis=evaluate_line(processed,v09,engine,mapping['champs_metier'])
            dossier['lignes']=mr
            for e in mis:issues.append({'pdf':v09.get('pdf'),'client_id':v09.get('client_id'),**e})
            for r in mr:
                for doc,c in r['cellules'].items():
                    longrows.append({'pdf':v09.get('pdf'),'client_id':v09.get('client_id'),
                      'champ_metier':r['champ_metier'],'libelle':r['libelle'],'document':doc,'reference':r['reference'],
                      'valeur_normalisee':c.get('valeur'),'valeur_brute':c.get('brut'),
                      'champ_source':'|'.join(c.get('champs_sources') or []),'page':c.get('page'),
                      'concordance':r['comparaison'].get(doc),'statut_extraction':c.get('etat'),
                      'confiance_p1':c.get('score_extraction'),'qualite_p2':c.get('score_qualite'),
                      'regle_normalisation':c.get('regle_normalisation'),'justification_qualite':c.get('raison_qualite')})
            for field in field_rows:
                detail.append({'pdf':v09.get('pdf'),**field})
            nb_ecarts=len(mis)
            status='A_CONTROLER' if nb_ecarts or anomalies or v09.get('anomalies') else 'LECTURE_SANS_ECART_DETECTE'
            dossier['statut_technique']=status
            summary.append({'pdf':v09.get('pdf'),'client_id':v09.get('client_id'),'reference_predom_candidate':v09.get('reference_predom_candidate'),
              'selection_v09':v09.get('selection'),'statut_technique':status,'nb_ecarts_comparatif':nb_ecarts,
              'nb_anomalies_part2':len(anomalies),'dq_score':dq.get('DQ_SCORE'),
              'validation_agence':'NON_EFFECTUEE','ca10':'ABSENT_NON_VERIFIE','cachet_dom':'SUSPENDU'})
        except Exception as exc:
            dossier['statut_technique']='ERREUR_TRAITEMENT'
            dossier['erreur']=f'{type(exc).__name__}: {exc}'
            errors.append({'pdf':v09.get('pdf'),'json':v09.get('json'),'erreur':dossier['erreur']})
            summary.append({'pdf':v09.get('pdf'),'client_id':v09.get('client_id'),'statut_technique':'ERREUR_TRAITEMENT','nb_ecarts_comparatif':'','nb_anomalies_part2':'', 'dq_score':'', 'validation_agence':'NON_EFFECTUEE','ca10':'ABSENT_NON_VERIFIE','cachet_dom':'SUSPENDU'})
        output.append(dossier)
    (target/'comparatif_dossiers_v10.json').write_text(json.dumps({'version':'V1.0','schema_part2_sha256':PART2_HASH,'dossiers':output},ensure_ascii=False,indent=2,default=str),encoding='utf8')
    save_csv(target/'synthese_v10.csv',summary,['pdf','client_id','reference_predom_candidate','selection_v09','statut_technique','nb_ecarts_comparatif','nb_anomalies_part2','dq_score','validation_agence','ca10','cachet_dom'])
    save_csv(target/'comparatif_valeurs_v10.csv',longrows,['pdf','client_id','champ_metier','libelle','document','reference','valeur_normalisee','valeur_brute','champ_source','page','concordance','statut_extraction','confiance_p1','qualite_p2','regle_normalisation','justification_qualite'])
    save_csv(target/'ecarts_cts_v10.csv',issues,['pdf','client_id','champ_metier','source','reference','valeur_source','valeur_reference','code'])
    (target/'erreurs_v10.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf8')
    (target/'champs_99_v15a.json').write_text(json.dumps(detail,ensure_ascii=False,default=str),encoding='utf8')
    print(f'V1.0 : dossiers={len(output)} | traités={len(output)-len(errors)} | erreurs={len(errors)} | écarts CTS={len(issues)}')
    print(f'Résultats : {target}')
    print('AUCUNE validation bancaire, aucun cachet DOM, aucune certification CA10.')
    return {'dossiers':output,'erreurs':errors,'ecarts':issues,'sortie':str(target)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description='TL-One V1.0 — analyse des JSON V15A + V0.9 sans modification')
    p.add_argument('--root',default='.',help='Racine contenant data/json et resultats/rapprochement_v08.csv')
    p.add_argument('--v09',default=None,help='Chemin optionnel du rapport CSV V0.9')
    p.add_argument('--part2',default=None,help='Notebook Partie 2 V15A vérifié (par défaut livré dans vendor)')
    x=p.parse_args()
    result = process(x.root,x.v09,x.part2)
    if result["erreurs"]:
        raise SystemExit(2)  # Rapports partiels conservés; aucune erreur silencieuse.
