"""Inventaire seulement : aucune association PDF-JSON présumée."""
import argparse,csv,json
from pathlib import Path

def inventory(root):
    root=Path(root)
    results=[]
    for kind, folder, suffixes in [('PDF',root/'data'/'pdf',{'.pdf'}),('JSON',root/'data'/'json',{'.json'})]:
        if not folder.exists():
            print('DOSSIER ABSENT:',folder)
            continue
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or p.suffix.lower() not in suffixes: continue
            record={'type':kind,'fichier':str(p.relative_to(root)),'nom_base':p.stem,'taille_octets':p.stat().st_size,'etat':'PRESENT'}
            if kind=='JSON':
                try:
                    data=json.loads(p.read_text(encoding='utf-8-sig'))
                    record['etat']='JSON_VALIDE' if isinstance(data,(dict,list)) else 'JSON_TYPE_INATTENDU'
                except Exception as e: record['etat']='JSON_INVALIDE: '+type(e).__name__
            results.append(record)
    dest=root/'resultats';dest.mkdir(exist_ok=True)
    with (dest/'inventaire_documents.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['type','fichier','nom_base','taille_octets','etat'],delimiter=';');w.writeheader();w.writerows(results)
    print('PDF:',sum(r['type']=='PDF' for r in results),'JSON:',sum(r['type']=='JSON' for r in results))
    print('Rapport:',dest/'inventaire_documents.csv')
    print('Aucun rapprochement automatique réalisé entre PDF, JSON et Prédom.')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(Path(__file__).resolve().parent));args=parser.parse_args();inventory(args.root)
