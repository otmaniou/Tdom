"""TL-One Prédom: test de sélection d'accords sans certification métier.

- Un client peut avoir plusieurs références DOM.
- Une seule référence *candidate* par client, sur statuts éligibles et date décision.
- Ne remplace pas la confrontation au CTS ni la validation humaine.
- Aucun service externe, aucun envoi de données.
"""
from __future__ import annotations
import argparse, csv, json, re, unicodedata
from collections import defaultdict, Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _empty(x):
    return x is None or (isinstance(x, str) and not x.strip())

def _txt(x):
    if x is None: return ""
    return x.strip() if isinstance(x, str) else str(x)

def _status(x):
    return " ".join(_txt(x).casefold().split())

def _date(x):
    if isinstance(x, datetime): return x
    if isinstance(x, date): return datetime.combine(x,datetime.min.time())
    if _empty(x): return None
    if isinstance(x, (int, float)):
        # Une date Excel non formatée comme date ne doit pas devenir une décision valide.
        return None
    text=_txt(x)
    try:
        return datetime.fromisoformat(text.replace('Z','+00:00')).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ('%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M','%d/%m/%Y',
                '%d-%m-%Y %H:%M:%S','%d-%m-%Y', '%Y-%m-%d'):
        try: return datetime.strptime(text,fmt)
        except ValueError: continue
    return None

def read_table(path: Path, header_row: int = 1, sheet: str | None = None):
    if header_row < 1: raise ValueError('header_row doit être >= 1')
    if not path.is_file(): raise FileNotFoundError(f'Fichier introuvable : {path}')
    suffix=path.suffix.lower()
    if suffix in ('.xlsx','.xlsm'):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError('Installer openpyxl : python -m pip install openpyxl') from exc
        wb=load_workbook(path, read_only=True, data_only=True)
        try:
            if sheet is not None and sheet not in wb.sheetnames:
                raise ValueError(f'Feuille inconnue {sheet!r} ; feuilles disponibles : {wb.sheetnames}')
            ws=wb[sheet] if sheet is not None else wb.active
            iterator=ws.iter_rows(values_only=True)
            for _ in range(header_row-1): next(iterator,None)
            headers=next(iterator,None)
            if headers is None: raise ValueError('Aucun en-tête à la ligne indiquée')
            headers=list(headers)
            # Ignorer uniquement les colonnes terminales réellement vides.
            while headers and _empty(headers[-1]): headers.pop()
            rows=[]
            for pos, values in enumerate(iterator, start=header_row+1):
                vals=list(values)[:len(headers)]
                vals += [None]*(len(headers)-len(vals))
                if all(_empty(v) for v in vals): continue
                rows.append((pos,vals))
        finally: wb.close()
    elif suffix=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as f:
            sample=f.read(4096)
            f.seek(0)
            try: dialect=csv.Sniffer().sniff(sample,delimiters=';,\t')
            except csv.Error: dialect=csv.excel
            reader=csv.reader(f,dialect)
            for _ in range(header_row-1): next(reader,None)
            headers=next(reader,None)
            if headers is None: raise ValueError('Aucun en-tête à la ligne indiquée')
            while headers and _empty(headers[-1]): headers.pop()
            rows=[]
            for pos, values in enumerate(reader,start=header_row+1):
                if len(values)>len(headers): raise ValueError(f'Ligne {pos}: plus de valeurs que d’en-têtes')
                vals=values + [None]*(len(headers)-len(values))
                if all(_empty(v) for v in vals): continue
                rows.append((pos,vals))
    else:
        raise ValueError('Format accepté : .xlsx, .xlsm ou .csv')
    if any(not isinstance(h,str) or not h.strip() for h in headers):
        raise ValueError('En-tête vide/non textuel dans le fichier')
    if len(set(headers))!=len(headers):
        raise ValueError('En-têtes dupliqués: pas de rapprochement possible')
    return headers,rows

def analyze(headers, rows, cfg: dict):
    """Sélection du dernier accord, sans fabriquer de référence DOM."""
    fields = cfg['colonnes']
    required = ('client_id', 'predom_reference', 'status', 'decision_date')
    missing = [f'{key}: {fields.get(key)!r}' for key in required
               if not isinstance(fields.get(key), str) or fields[key] not in headers]
    if missing:
        raise ValueError('Colonnes exactes absentes: ' + ', '.join(missing) + '\nEn-têtes trouvés: ' + repr(headers))
    dom_col = fields.get('dom_reference')
    if dom_col and dom_col not in headers:
        raise ValueError('Colonne DOM configurée mais absente: ' + repr(dom_col))
    allowed = {_status(x) for x in cfg['statuts_eligibles']}
    by_client = defaultdict(list)
    records = []
    for pos, vals in rows:
        raw = dict(zip(headers, vals))
        client = raw[fields['client_id']]
        predom = raw[fields['predom_reference']]
        dom = raw[dom_col] if dom_col else None
        status = raw[fields['status']]
        dt = _date(raw[fields['decision_date']])
        issues = []
        if _empty(client): issues.append('CLIENT_ABSENT')
        elif isinstance(client, (int,float)): issues.append('CLIENT_NUMERIQUE_ZEROS_A_VERIFIER')
        if _empty(predom): issues.append('REFERENCE_PREDOM_ABSENTE')
        elif isinstance(predom, (int,float)): issues.append('PREDOM_NUMERIQUE_ZEROS_A_VERIFIER')
        if dt is None: issues.append('DATE_DECISION_ABSENTE_OU_ILLISIBLE')
        eligible = _status(status) in allowed
        if not eligible: issues.append('STATUT_NON_ELIGIBLE')
        if _status(status) == _status('Accord Prédom') and not _empty(dom):
            issues.append('DOM_PRESENTE_AVANT_CREATION_A_VERIFIER')
        if _status(status) == _status('Domicilié') and _empty(dom):
            issues.append('DOM_ABSENTE_POUR_STATUT_DOMICILIE')
        usable = eligible and dt is not None and not _empty(client) and not _empty(predom) and not isinstance(client,(int,float)) and not isinstance(predom,(int,float))
        record = {'ligne_excel':pos, 'client':_txt(client), 'reference_predom':_txt(predom),
                  'reference_dom':_txt(dom), 'statut':_txt(status),
                  'request_decision_date_brute':_txt(raw[fields['decision_date']]),
                  'request_decision_date_iso':dt.isoformat(sep=' ') if dt else '',
                  'eligible':eligible,'candidate_comparable':usable,'anomalies':issues,'selection':'NON_RETENUE'}
        records.append(record)
        if record['client']: by_client[record['client']].append(record)
    summary=[]
    for client,items in sorted(by_client.items()):
        candidates=[x for x in items if x['candidate_comparable']]
        latest=[]; selected=None
        if not candidates:
            state='AUCUN_ACCORD_ELIGIBLE'
        else:
            date_max=max(x['request_decision_date_iso'] for x in candidates)
            latest=[x for x in candidates if x['request_decision_date_iso']==date_max]
            refs={x['reference_predom'] for x in latest}
            if len(refs)!=1:
                state='AMBIGUITE_MEME_DATE'
                for x in latest:x['selection']='AMBIGUE'
            else:
                selected=latest[0]
                state='PROPOSEE_A_CONFRONTER_CTS'
                for x in latest:x['selection']='PROPOSEE'
        summary.append({'client':client,'nb_lignes_historique':len(items),
                        'reference_predom_proposee':selected['reference_predom'] if selected else '',
                        'reference_dom':selected['reference_dom'] if selected else '',
                        'statut_selection':state,'statut_predom':selected['statut'] if selected else '',
                        'date_derniere_decision':selected['request_decision_date_iso'] if selected else '',
                        'ca10':'ABSENT_NON_VERIFIE','validation_dossier':'NON_EFFECTUEE',
                        'controle_cts':'NON_EFFECTUE','cachet_dom':'SUSPENDU'})
    return {'nb_lignes':len(records),'nb_clients':len(by_client),
            'bilan_statuts':dict(Counter(x['statut'] for x in records)),
            'dossiers':summary,'historique_predom':records,
            'note':'Candidat Prédom uniquement; aucune correspondance CTS/PDF/JSON ni validation de signature.'}

def dump_csv(path,rows):
    if not rows: return
    keys=list(rows[0].keys())
    with path.open('w', encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys,delimiter=';')
        writer.writeheader()
        for row in rows:
            writer.writerow({k:('|'.join(row[k]) if isinstance(row[k],list) else row[k]) for k in keys})

def run(path, config_path=None, output=None):
    cfg=json.loads(Path(config_path or ROOT/'config_predom.json').read_text(encoding='utf-8'))
    headers,rows=read_table(Path(path),header_row=cfg.get('header_row',1),sheet=cfg.get('sheet_name'))
    result=analyze(headers,rows,cfg)
    dest=Path(output or ROOT/'resultats')
    dest.mkdir(parents=True,exist_ok=True)
    (dest/'rapport_predom.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    dump_csv(dest/'selection_predom.csv',result['dossiers'])
    dump_csv(dest/'historique_predom.csv',result['historique_predom'])
    print(f"Lignes: {result['nb_lignes']} | Clients: {result['nb_clients']}")
    for status,count in Counter(s['statut_selection'] for s in result['dossiers']).items():print(f'  {status}: {count}')
    print('CA10 : ABSENT_NON_VERIFIE (pour tous les dossiers de ce pilote)')
    print('Dossier pilote : aucune validation officielle, aucun cachet, aucun Planning TL.')
    print('Rapports:', dest.resolve())
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description='TL-One: pilote Prédom, sans certification')
    p.add_argument('fichier',help='Export Prédom .xlsx / .xlsm / .csv')
    p.add_argument('--config',default=str(ROOT/'config_predom.json'))
    p.add_argument('--output',default=str(ROOT/'resultats'))
    args=p.parse_args()
    run(args.fichier,args.config,args.output)
