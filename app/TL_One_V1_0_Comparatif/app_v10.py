"""Interface exploratoire en lecture seule TL-One V1.0.
Lancer : streamlit run app_v10.py -- --root /mnt/TL_One_Test_Predom_V0_6
"""
import argparse
import html
import json
import os
from pathlib import Path

import streamlit as st
from tl_one_v10 import ORDER, under_root

parser=argparse.ArgumentParser(add_help=False)
parser.add_argument('--root',default=os.environ.get('TL_ONE_ROOT','/mnt/TL_One_Test_Predom_V0_6'))
args,_=parser.parse_known_args()
root=Path(args.root).resolve()
file=root/'resultats/v10/comparatif_dossiers_v10.json'

st.set_page_config(page_title='TL-One DOM | V1.0',page_icon='📄',layout='wide')
st.markdown('''<style>
.block-container {padding-top:1.8rem;max-width:1600px}
.tl-table {width:100%;border-collapse:collapse;font-size:.81rem}
.tl-table th,.tl-table td {border-bottom:1px solid rgba(127,127,127,.3);padding:.65rem .52rem;vertical-align:top}
.tl-table th {background:rgba(127,127,127,.13);position:sticky;top:0}
.tl-table th:nth-child(2) {background:rgba(53,115,175,.14)}
.tl-val {font-weight:600;cursor:help;white-space:normal;word-break:break-word}
.tl-sub {display:block;font-size:.66rem;opacity:.65;margin-top:4px}
.tl-warn {color:#c77600}.tl-bad {color:#c44545}.tl-ok {color:#18836b}.tl-muted {opacity:.45}
.tl-header{margin:.5rem 0 1.5rem}
</style>''',unsafe_allow_html=True)

st.title('TL-One · Contrôle documentaire DOM')
st.caption('Consultation V1.0 · CTS = référence contractuelle · Prédom = dossier candidat · Aucune validation ni cachet automatisés')
if not file.exists():
    st.error(f'Rapport V1.0 introuvable : {file}')
    st.code(f'python tl_one_v10.py --root {root}')
    st.stop()

try: payload=json.loads(file.read_text(encoding='utf8'))
except (ValueError,OSError) as e:
    st.error(f'Fichier V1.0 invalide : {e}');st.stop()
dossiers=payload.get('dossiers') or []
if not dossiers:
    st.warning('Aucun dossier analysé');st.stop()

n_errors=sum(d.get('statut_technique')=='ERREUR_TRAITEMENT' for d in dossiers)
n_alert=sum(d.get('statut_technique')=='A_CONTROLER' for d in dossiers)
a,b,c,d=st.columns(4)
a.metric('Dossiers',len(dossiers));b.metric('À contrôler',n_alert);c.metric('Erreurs techniques',n_errors);d.metric('CA10 disponible',0)

filter_state=st.selectbox('Filtrer le traitement', ['Tous','À contrôler','Sans écart détecté','Erreurs techniques'])
filtered=[x for x in dossiers if filter_state=='Tous' or
          (filter_state=='À contrôler' and x.get('statut_technique')=='A_CONTROLER') or
          (filter_state=='Sans écart détecté' and x.get('statut_technique')=='LECTURE_SANS_ECART_DETECTE') or
          (filter_state=='Erreurs techniques' and x.get('statut_technique')=='ERREUR_TRAITEMENT')]
if not filtered:
    st.info('Aucun dossier dans ce filtre');st.stop()
selected=st.selectbox('Dossier à examiner',range(len(filtered)),format_func=lambda i: f"{filtered[i].get('client_id') or 'Sans identifiant'} · {Path(filtered[i].get('pdf') or '').name} · {filtered[i].get('statut_technique')}")
doc=filtered[selected]
left,right=st.columns([1.7,1],gap='large')
with left:
    st.subheader('Comparatif des données extraites')
    st.caption('Survolez une valeur : valeur brute, normalisation, confiance extraction, fiabilité règles, page et comparaison.')
    badges=f"Prédom : {html.escape(str(doc.get('reference_predom_candidate') or 'Non sélectionnée'))} | Date décision : {html.escape(str(doc.get('date_decision') or '—'))}"
    st.info(badges)
    if doc.get('statut_technique')=='ERREUR_TRAITEMENT':
        st.error(doc.get('erreur','Erreur sans détail'))
    else:
        groups=sorted({r.get('groupe','Divers') for r in doc.get('lignes') or []})
        grp=st.selectbox('Groupe de champs',['Tous']+groups)
        lines=doc.get('lignes') or []
        if grp!='Tous':lines=[r for r in lines if r.get('groupe')==grp]
        buf=['<table class="tl-table"><thead><tr><th>Champ métier</th>']
        for col in ORDER:buf.append(f'<th>{html.escape(col)}</th>')
        buf.append('</tr></thead><tbody>')
        for row in lines:
            buf.append('<tr><td><strong>'+html.escape(str(row.get('libelle') or row['champ_metier']))+'</strong></td>')
            for col in ORDER:
                x=row.get('cellules',{}).get(col) or {}
                state=row.get('comparaison',{}).get(col) or ''
                value=x.get('valeur')
                value_s='—' if value is None or value=='' else str(value)
                details=[('Champ OCR',', '.join(x.get('champs_sources') or [])),('Valeur lue',x.get('brut')),
                         ('Valeur normalisée',value),('Indice extraction V15A',x.get('score_extraction')),
                         ('Fiabilité DQ V15A',x.get('score_qualite')),('Base confiance',x.get('raison_extraction')),
                         ('Motif fiabilité',x.get('raison_qualite')),('Normalisation',x.get('regle_normalisation')),
                         ('Page PDF',x.get('page')),('Comparaison',state)]
                tooltip='\n'.join(f'{k} : {v}' for k,v in details if v is not None and v!='')
                css='tl-bad' if state in ('ECART','ANOMALIE_VERSIONS') else 'tl-ok' if state in ('CONFORME','REFERENCE') else 'tl-muted' if state in ('NON_APPLICABLE','NON_EXTRAIT_VOLONTAIREMENT') else 'tl-warn'
                buf.append(f'<td><span class="tl-val {css}" title="{html.escape(tooltip,quote=True)}">{html.escape(value_s)}</span><span class="tl-sub">{html.escape(state)}</span></td>')
            buf.append('</tr>')
        buf.append('</tbody></table>')
        st.markdown(''.join(buf),unsafe_allow_html=True)
        with st.expander('Anomalies Partie 2 V15A'):
            anomalies=doc.get('anomalies_v15a') or []
            st.json(anomalies if anomalies else {'message':'Aucune anomalie répertoriée par Partie 2'})
        with st.expander('Qualité du dossier'):
            st.json(doc.get('dq_summary') or {})
with right:
    st.subheader('Pièces et contrôles')
    st.warning('CA10 absent — signature non vérifiée via le spécimen.')
    st.caption('Cachet DOM suspendu. Référence DOM non présumée à partir de Prédom.')
    st.write('**CTS :** référence métier pour les champs contractuels. **TTR :** preuve propre au permis de travail.')
    pdf_relative=doc.get('pdf')
    if pdf_relative:
        try:
            pdf=under_root(root,pdf_relative)
            if not pdf or not pdf.is_file():
                st.warning('PDF original non disponible à ce chemin')
            else:
                import fitz
                with fitz.open(str(pdf)) as handle:
                    page_idx=st.number_input('Page PDF',min_value=1,max_value=len(handle),value=1,step=1)
                    page=handle[int(page_idx)-1]
                    pix=page.get_pixmap(matrix=fitz.Matrix(1.15,1.15),alpha=False)
                    st.image(pix.tobytes('png'),use_container_width=True)
        except ImportError:
            st.info('Installer pymupdf pour l’aperçu PDF : pip install pymupdf')
        except Exception as exc:
            st.warning('Aperçu PDF indisponible : '+type(exc).__name__)
    else:st.warning('Chemin PDF non disponible')
    with st.expander('Rapprochement Prédom V0.9'):
        st.json({'client_id':doc.get('client_id'),'reference_predom_candidate':doc.get('reference_predom_candidate'),
                 'selection_v09':doc.get('selection_v09'),'date_decision':doc.get('date_decision'),
                 'anomalies_v09':doc.get('anomalies_v09')})
st.divider()
st.caption('TL-One V1.0 est un outil de contrôle exploratoire en lecture seule. Les signatures, validations, corrections et rejets nécessitent une étape ultérieure avec audit.')
