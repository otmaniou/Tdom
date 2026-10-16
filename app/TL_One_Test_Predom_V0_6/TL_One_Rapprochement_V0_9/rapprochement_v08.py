"""TL-One V0.9: rapprochement prudent PDF/JSON/Prédom; aucune validation automatique."""
import argparse,csv,json,re,unicodedata
from pathlib import Path
from difflib import SequenceMatcher
from collections import defaultdict
from predom_pilot import read_table,_date,_status

def normalize_header(value):
    return " ".join(unicodedata.normalize("NFKC",str(value)).replace("\xa0"," ").split()).casefold()

def resolve_header(headers,wanted):
    if not wanted:return None
    found=[h for h in headers if normalize_header(h)==normalize_header(wanted)]
    if len(found)>1:raise ValueError("En-têtes ambigus: "+repr(found))
    return found[0] if found else None


def txt(x):
    if x is None: return ''
    if isinstance(x,float) and x.is_integer():return str(int(x))
    return str(x).strip()

def account_to_id(account):
    """Compte bancaire: 15 premiers chiffres, puis 11 derniers = identifiant client."""
    s=txt(account)
    if not re.fullmatch(r"\d{15,}",s):
        return None
    return s[:15][-11:]

def pdf_account(filename):
    """Compte en tête de nom PDF, indépendant du suffixe (AUG, dom, etc.)."""
    nom=Path(filename).name
    if not nom.lower().endswith(".pdf"):
        return None
    m=re.match(r"^(\d{15,})(?=[-_ .]|$)",nom)
    if not m:
        return None
    period=re.match(r'^\d{15,}-(\d{6})-',nom)
    if period and not (1 <= int(period.group(1)[4:]) <= 12):
        return None
    return m.group(1)

def normalize_client_id(value):
    """Prédom: identifiant bancaire de 11 chiffres; pas de conversion en float."""
    s=txt(value)
    return s if re.fullmatch(r"\d{11}",s) else None

def normalize_name(value):
    s=unicodedata.normalize('NFKD',txt(value)).upper()
    s=''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[A-Z0-9]+',s))

def name_score(a,b):
    a,b=normalize_name(a),normalize_name(b)
    if not a or not b:return None
    a_sorted=' '.join(sorted(a.split()));b_sorted=' '.join(sorted(b.split()))
    return round(100*max(SequenceMatcher(None,a,b).ratio(),SequenceMatcher(None,a_sorted,b_sorted).ratio()),1)

def recursive_fields(obj,wanted):
    hits=[]
    def walk(x,path='',depth=0):
        if depth>30:return
        if isinstance(x,dict):
            for k,v in x.items():
                if k in wanted:
                    value=v
                    if isinstance(v,dict):
                        value=next((v[z] for z in ('normalized_value','valeur_normalisee','value','valeur','raw_value','raw') if z in v),None)
                    if not isinstance(value,(dict,list)) and value is not None:hits.append((k,txt(value),path+'/'+k))
                walk(v,path+'/'+k,depth+1)
        elif isinstance(x,list):
            for i,v in enumerate(x):walk(v,path+'/'+str(i),depth+1)
    walk(obj)
    return hits

def pick_field(hits,key):
    vals={v for k,v,_ in hits if k==key and v}
    if len(vals)==1:return next(iter(vals)),'OK'
    if len(vals)>1:return '', 'AMBIGU_'+key
    return '', 'ABSENT_'+key

def load_predom(path,cfg):
    h,rows=read_table(Path(path),cfg.get('header_row',1),cfg.get('sheet_name'))
    col=dict(cfg['colonnes']); required=('client_id','predom_reference','status','name')
    col={k:resolve_header(h,v) for k,v in col.items()}
    if not col.get('decision_date'):
        col['decision_date']=resolve_header(h,'Request Decision Date')
    missing=[f'{k}={cfg["colonnes"].get(k)!r}' for k in required if not col.get(k)]
    if missing:raise ValueError('Colonnes Prédom absentes: '+', '.join(missing)+'; disponibles: '+repr(h))
    dc=col.get('decision_date'); has_date=bool(dc and dc in h)
    by=defaultdict(list)
    for line,values in rows:
        raw=dict(zip(h,values)); raw_cid=txt(raw[col['client_id']]); cid=normalize_client_id(raw_cid); issues=[]
        if isinstance(raw[col['client_id']],(float,int)):issues.append('IDENTIFIANT_NUMERIQUE_VERIFIER_ZEROS')
        if not cid:issues.append('IDENTIFIANT_CLIENT_PREDOM_INVALIDE_11_CHIFFRES')
        status=txt(raw[col['status']]);eligible=_status(status) in {_status(s) for s in cfg['statuts_eligibles']}
        dt=_date(raw[dc]) if has_date else None
        rec={'ligne_excel':line,'client_id':cid,'reference_predom':txt(raw[col['predom_reference']]),'statut':status,'nom_predom':txt(raw[col['name']]),'date_decision':dt.isoformat() if dt else '', 'eligible':eligible,'anomalies':issues}
        if not has_date:rec['anomalies'].append('COLONNE_DATE_DECISION_ABSENTE')
        elif not dt:rec['anomalies'].append('DATE_DECISION_ABSENTE_OU_INVALIDE')
        if cid:by[cid].append(rec)
    return by,has_date,len(rows)

def run(root,predom,config):
    root=Path(root);cfg=json.loads(Path(config).read_text(encoding='utf8'))
    by,has_date,nb_rows=load_predom(predom,cfg)
    pdfs=sorted(p for p in (root/'data/pdf').rglob('*') if p.is_file() and p.suffix.lower()=='.pdf' and '.ipynb_checkpoints' not in p.parts)
    jsons=sorted(p for p in (root/'data/json').rglob('*') if p.is_file() and p.suffix.lower()=='.json' and '.ipynb_checkpoints' not in p.parts)
    json_by_stem=defaultdict(list)
    for p in jsons:json_by_stem[p.stem.casefold()].append(p)
    report=[]; used=set()
    for pdf in pdfs:
        anomalies=[];account=pdf_account(pdf.name);cid=account_to_id(account) if account else None
        if not account:anomalies.append('NOM_PDF_FORMAT_INATTENDU')
        elif not cid:anomalies.append('COMPTE_PDF_INVALIDE')
        matches=json_by_stem.get(pdf.stem.casefold(),[])
        if len(matches)!=1:anomalies.append('JSON_ABSENT_OU_MULTIPLE_MEME_NOM')
        jpath=matches[0] if len(matches)==1 else None
        cts_name='';ocr_account='';ocr_id=None
        if jpath:
            used.add(jpath)
            try:
                obj=json.loads(jpath.read_text(encoding='utf-8-sig'))
                hits=recursive_fields(obj,{'DOM_COMPTE_LOCAL','CTS_NOM_PRENOM_TRAVAILLEUR'})
                ocr_account,state=pick_field(hits,'DOM_COMPTE_LOCAL');cts_name,state2=pick_field(hits,'CTS_NOM_PRENOM_TRAVAILLEUR')
                if state!='OK':anomalies.append(state)
                if state2!='OK':anomalies.append(state2)
                ocr_id=account_to_id(ocr_account)
                if account and ocr_account and account!=ocr_account:anomalies.append('ECART_COMPTE_PDF_QWEN')
            except Exception as e:anomalies.append('JSON_ILLISIBLE_'+type(e).__name__)
        # Secours Qwen uniquement si le nom PDF ne fournit pas la clé; pas de validation automatique.
        source='PDF' if cid else ('QWEN_SECOURS_A_VERIFIER' if ocr_id else 'ABSENTE')
        cid=cid or ocr_id
        candidates=by.get(cid,[]) if cid else []
        eligible=[dict(c,score_nom=name_score(cts_name,c['nom_predom'])) for c in candidates if c['eligible']]
        if not candidates:anomalies.append('AUCUN_CLIENT_PREDOM')
        elif not eligible:anomalies.append('AUCUN_STATUT_PREDOM_ELIGIBLE')
        chosen=[]
        if eligible and has_date:
            dated=[c for c in eligible if c['date_decision']]
            if dated:
                max_date=max(c['date_decision'] for c in dated)
                chosen=[c for c in dated if c['date_decision']==max_date]
                if len(chosen)>1:
                    anomalies.append('AMBIGUITE_DERNIERE_DECISION')
                    chosen=[]
            else:anomalies.append('DATE_DECISION_INDISPONIBLE')
        elif eligible:anomalies.append('DATE_DECISION_COLONNE_MANQUANTE_SELECTION_INTERDITE')
        if chosen and not chosen[0]['reference_predom']:
            anomalies.append('REFERENCE_PREDOM_ABSENTE');chosen=[]
        if chosen and chosen[0]['score_nom'] is None:anomalies.append('SCORE_NOM_IMPOSSIBLE')
        if chosen and chosen[0]['score_nom'] is not None and chosen[0]['score_nom']<cfg.get('seuil_nom_a_verifier',85):anomalies.append('NOM_CTS_PREDOM_A_VERIFIER')
        if source!='PDF':anomalies.append('CLE_SECOURS_OU_ABSENTE_VALIDATION_HUMAINE')
        row={'pdf':str(pdf.relative_to(root)),'json':str(jpath.relative_to(root)) if jpath else '',
             'compte_pdf':account or '', 'compte_qwen':ocr_account,'client_id':cid or '', 'source_client_id':source,
             'nom_cts':cts_name,'nombre_predom_client':len(candidates),'nombre_predom_eligibles':len(eligible),
             'meilleur_score_nom_parmi_eligibles':max((c['score_nom'] for c in eligible if c['score_nom'] is not None),default=''),
             'reference_predom_candidate':chosen[0]['reference_predom'] if len(chosen)==1 else '',
             'statut_predom':chosen[0]['statut'] if len(chosen)==1 else '',
             'date_decision':chosen[0]['date_decision'] if len(chosen)==1 else '',
             'nom_predom':chosen[0]['nom_predom'] if len(chosen)==1 else '',
             'score_nom':chosen[0]['score_nom'] if len(chosen)==1 else '',
             'reference_dom':'','ca10':'ABSENT_NON_VERIFIE','cachet_dom':'SUSPENDU',
             'validation':'NON_EFFECTUEE','selection':'CANDIDAT_A_VERIFIER' if len(chosen)==1 else 'AUCUNE_SELECTION_AUTOMATIQUE','anomalies':'|'.join(sorted(set(anomalies)))}
        report.append(row)
    dest=root/'resultats';dest.mkdir(parents=True,exist_ok=True)
    out=dest/'rapprochement_v08.csv'
    if report:
        with out.open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(report[0]),delimiter=';');w.writeheader();w.writerows(report)
    missing=[str(p.relative_to(root)) for p in jsons if p not in used]
    (dest/'rapport_rapprochement_v08.json').write_text(json.dumps({'nb_lignes_predom':nb_rows,'nb_pdf':len(pdfs),'nb_json':len(jsons),'date_decision_disponible':has_date,'json_non_associes':missing,'dossiers':report},ensure_ascii=False,indent=2),encoding='utf8')
    print(f'Prédom: {nb_rows} lignes | PDF: {len(pdfs)} | JSON: {len(jsons)}')
    print(f'Dossiers analysés: {len(report)} | JSON non associés: {len(missing)}')
    print('Rapports:',out, 'et rapport_rapprochement_v08.json')
    print('Aucune validation bancaire, aucun cachet DOM, aucun rapprochement présumé sans preuve.')
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',default=str(Path(__file__).resolve().parent));ap.add_argument('--predom',required=True);ap.add_argument('--config',default=str(Path(__file__).resolve().parent/'config_predom.json'))
    a=ap.parse_args();run(a.root,a.predom,a.config)
