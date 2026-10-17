"""Écran de validation des domiciliations : liste des dossiers → matrice → page du PDF."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from . import matrice as mx
from .common import audit, current_user, find_pdf, is_blank, page_count, render_page

RED, GREY = "#B3261E", "#6B7470"
FEU = {"r": "🔴 Anomalie", "o": "🟠 À vérifier", "v": "🟢 OK", "x": "⚫ Rejeté"}
FILTRES = ["À traiter", "Prêts à valider", "Traités", "Tous"]


def _W():
    from .ui import W
    return W


def _mt(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_resource(show_spinner="Construction des matrices…", max_entries=4)
def _matrices(_P, key: tuple):
    lot = mx.load_lot(_P)
    ms = mx.build_all(lot, mx.read_journal(_P.dom_journal), mx.default_sources(_P.sources_reference_xlsx))
    return lot, ms


def load(P):
    key = tuple(_mt(p) for p in (P.fields_csv, P.dossiers_csv, P.carthago_match_csv, P.validation_xlsx,
                                 P.dom_journal, P.sources_reference_xlsx)) + (str(P.data_root),)
    return _matrices(P, key)


def _event(P, fichier, action, **kw):
    mx.append_event(P.dom_journal, current_user(), fichier, action, **kw)
    audit(P.audit_log, f"DOM_MATRICE_{action}", current_user(), fichier=fichier, **kw)


# ----------------------------------------------------------------------------- liste
def render_list(P, ms: list[dict]):
    if not ms:
        st.info("Aucun dossier : lancez la Partie 2 (onglet ① Traitement).")
        return
    rows = [mx.summary(m) for m in ms]
    df = pd.DataFrame(rows)
    rank = {"r": 0, "o": 1, "v": 2, "x": 3}
    done = df["STATUT"].str.startswith(("Validé", "Rejeté"))
    df["_k"] = [(1 if d else 0, rank[f], fi if fi is not None else 0) for d, f, fi in
                zip(done, df["FEU"], df["FIABILITE"])]
    df = df.sort_values("_k").drop(columns="_k").reset_index(drop=True)
    done = df["STATUT"].str.startswith(("Validé", "Rejeté"))

    n = len(df)
    c = st.columns(5)
    c[0].metric("Dossiers", n)
    c[1].metric("Avec anomalies", int(((df["A_REVOIR"] > 0) & ~done).sum()))
    c[2].metric("Prêts à valider", int(((df["A_REVOIR"] == 0) & ~done).sum()))
    c[3].metric("Validés", int(df["STATUT"].eq("Validé").sum()))
    c[4].metric("Rejetés", int(df["STATUT"].str.startswith("Rejeté").sum()))

    f1, f2 = st.columns([3, 2])
    filt = f1.segmented_control("Afficher", FILTRES, default="À traiter", key="dom_filtre") or "Tous"
    q = f2.text_input("Rechercher", placeholder="Nom ou identifiant client", key="dom_q")
    view = df
    if filt == "À traiter":
        view = df[(df["A_REVOIR"] > 0) & ~done]
    elif filt == "Prêts à valider":
        view = df[(df["A_REVOIR"] == 0) & ~done]
    elif filt == "Traités":
        view = df[done]
    if q:
        ql = q.strip().lower()
        view = view[view["NOM"].fillna("").str.lower().str.contains(ql, regex=False)
                    | view["IDENTIFIANT_CLIENT"].fillna("").str.contains(ql, regex=False)]
    if view.empty:
        st.caption("Aucun dossier pour ce filtre.")
        return
    show = pd.DataFrame({
        "État": view["FEU"].map(FEU), "Client": view["NOM"], "Identifiant client": view["IDENTIFIANT_CLIENT"],
        "Compte": view["COMPTE"], "Début permis": view["DEBUT"], "Fin permis": view["FIN"],
        "Part transférable": view["PART"], "Taux": view["TAUX"], "N° permis": view["PERMIS"],
        "Type": view["TYPE"], "Fiabilité": view["FIABILITE"], "Cases à revoir": view["A_REVOIR"],
        "Bloquants": view["BLOQUANTS"],
        "Carthago": view["CARTHAGO"], "Statut": view["STATUT"], "Fichier": view["FICHIER"],
    }).reset_index(drop=True)
    red_map = {"Début permis": "debut_permis", "Fin permis": "fin_permis", "Part transférable": "part",
               "Taux": "taux", "N° permis": "permis", "Client": "nom", "Compte": "compte"}
    reds = list(view["_red"])
    car_red = list(view["CARTHAGO"].eq("Non trouvé"))

    def color(col):
        out = []
        for i, v in enumerate(col):
            bad = False
            if col.name in red_map:
                bad = reds[i].get(red_map[col.name], False)
            elif col.name == "Fiabilité":
                bad = v is not None and not pd.isna(v) and float(v) < 70
            elif col.name in ("Cases à revoir", "Bloquants"):
                bad = v > 0
            elif col.name == "Carthago":
                bad = car_red[i]
            out.append(f"color: {RED}; font-weight: 600" if bad else "")
        return out
    sty = show.style.apply(color, axis=0)
    ev = st.dataframe(sty, hide_index=True, on_select="rerun", selection_mode="single-row",
                      key=f"dom_list_{st.session_state.get('dom_nonce', 0)}",
                      height=min(42 + 35 * len(show), 640),
                      column_config={"Fiabilité": st.column_config.NumberColumn(
                          help="Indice qualité 0–100 de la Partie 2 (lecture, normalisation, cohérence). "
                               "Ce n'est pas une probabilité."),
                          "Fichier": st.column_config.TextColumn(width="small")}, **_W())
    st.caption("Cliquez sur une ligne pour ouvrir le dossier. Texte rouge = anomalie.")
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        st.session_state["dom_sel"] = show.loc[sel[0], "Fichier"]
        st.session_state["dom_order"] = list(show["Fichier"])
        st.session_state.pop("dom_cell", None)
        st.rerun()


# ----------------------------------------------------------------------------- matrice
def _matrix_frame(m: dict):
    labels, data, styles = [], [], []
    for x in m["rows"]:
        lg = x["ligne"]
        line, sty = {}, {}
        for c in mx.COLS:
            cell = x["cells"][c]
            if lg.sources.get(c) is None:
                line[mx.COL_LABEL[c]], sty[mx.COL_LABEL[c]] = "", ""
                continue
            txt = cell["text"]
            if txt is None and cell.get("a_extraire"):
                line[mx.COL_LABEL[c]] = "à extraire"
                sty[mx.COL_LABEL[c]] = f"color: {GREY}; font-style: italic"
                continue
            if txt is None:
                line[mx.COL_LABEL[c]] = "—"
                sty[mx.COL_LABEL[c]] = f"color: {RED}; font-weight: 600" if cell["open"] else f"color: {GREY}"
                continue
            if cell["edit"] is not None:
                txt += " ✎" if cell["edit"]["action"] == "CORRIGE" else " ✓"
            if c == x["ref"]:
                txt = "◆ " + txt
            line[mx.COL_LABEL[c]] = txt
            css = []
            if cell["open"]:
                css.append(f"color: {RED}; font-weight: 600")
            if cell["edit"] is not None and cell["edit"]["action"] == "CORRIGE":
                css.append("font-style: italic")
            sty[mx.COL_LABEL[c]] = "; ".join(css)
        line["Retenu (Planning)"] = x["retenu_txt"] or ("—" if lg.ref else "")
        sty["Retenu (Planning)"] = f"color: {RED}; font-weight: 600" if x["missing_ref"] else "font-weight: 600"
        line["Cohérence"] = x["coh"]
        sty["Cohérence"] = f"color: {RED}; font-weight: 600" if x["n_open"] else ""
        labels.append(lg.label + (" ⚑" if lg.vigilance else ""))
        data.append(line)
        styles.append(sty)
    df = pd.DataFrame(data, index=labels)
    st_df = pd.DataFrame(styles, index=labels)
    return df, df.style.apply(lambda _: st_df, axis=None)


def _after(m, lk, col, suivante: bool):
    """Après une correction : rouvre la case suivante en anomalie (validation en chaîne)."""
    opens = [(r["ligne"].key, c) for r in m["rows"] for c in mx.COLS
             if r["cells"][c]["open"] and (r["ligne"].key, c) != (lk, col)]
    if suivante and opens:
        st.session_state["dom_cell_force"] = opens[0]
    st.rerun()


@st.dialog("Vérification de la case", width="large")
def _cell_dialog(P, m: dict, lk: str, col: str):
    _cell_panel(P, m, lk, col)


def _cell_panel(P, m: dict, lk: str, col: str):
    x = next(r for r in m["rows"] if r["ligne"].key == lk)
    lg, cell = x["ligne"], x["cells"][col]
    st.markdown(f"### {lg.label} · {mx.COL_LABEL[col]}" + (" · ◆ référence" if x["ref"] == col else ""))
    gauche, droite = st.columns([2, 3], gap="medium")
    with gauche:
        _cell_infos(P, m, x, lg, cell, lk, col)
    with droite:
        _cell_page(P, m, cell, col)


def _cell_infos(P, m, x, lg, cell, lk, col):
    fichier = m["fichier"]
    info = [("Valeur lue (OCR)", cell["raw"]), ("Valeur normalisée", cell["text"]),
            ("Page", cell["page"]), ("Confiance", None if cell["conf"] is None else
                                     f"{cell['conf']:.0f}" + (f" · {cell['level']}" if cell["level"] else "")),
            ("Règle", mx.RULES_LIGNE.get(lg.key) or mx.RULES.get(lg.kind)), ("Valeur retenue", x["retenu_txt"])]
    if cell.get("a_extraire"):
        st.info("Donnée demandée par l'agence mais pas encore extraite par la Partie 1 (à ajouter au prompt).")
    if cell.get("carthago_status"):
        info.append(("Statut Carthago", mx.CARTHAGO_MSG.get(cell["carthago_status"], cell["carthago_status"])))
    st.dataframe(pd.DataFrame([(k, "" if is_blank(v) else str(v)) for k, v in info], columns=["", "Valeur"]),
                 hide_index=True, **_W())
    for kind, msg in cell["issues"]:
        lab = {"bloq": "Bloquant : ", "incoh": "Anomalie : "}.get(kind, "À vérifier : ")
        (st.error if cell["open"] else st.caption)(lab + msg + ("" if cell["open"] else " — traité"))
    if cell["open"] and cell["bloq"]:
        st.caption("Une anomalie bloquante ne se lève pas par confirmation : corrigez la valeur si la lecture "
                   "est fausse, sinon rejetez le dossier.")
    if cell["edit"] is not None:
        e = cell["edit"]
        st.caption(f"{'Corrigé' if e['action'] == 'CORRIGE' else 'Lecture confirmée'} par {e.get('user')} "
                   f"le {e.get('ts', '')[:16].replace('T', ' ')}"
                   + (f" (valeur précédente : {e.get('valeur_precedente')})" if e.get("valeur_precedente") else ""))

    decided = m["decision"] is not None
    k = f"{fichier}|{lk}|{col}"
    if col == "CARTHAGO" and not decided:
        st.info("CarthagoDom est un référentiel : il ne se corrige pas ici. Mettez à jour l'export Carthago "
                "(onglet ① Traitement) puis relancez la Partie 2, ou rejetez le dossier.")
        decided = True
    if not decided:
        if lg.kind == "bool":
            cur = mx.to_bool(cell["value"])
            new = st.radio("Corriger la valeur", ["True", "False"], index=0 if cur is not False else 1,
                           format_func=lambda v: "Présente" if v == "True" else "Absente", horizontal=True,
                           key=f"corr_{k}")
        else:
            new = st.text_input("Corriger la valeur", value="" if is_blank(cell["value"]) else str(cell["value"]),
                                key=f"corr_{k}")
        suivante = st.checkbox("Ouvrir ensuite la case suivante en anomalie", value=True, key=f"chain_{fichier}")
        if st.button("Enregistrer la correction", type="primary", key=f"save_{k}", **_W()):
            if is_blank(new):
                st.warning("Saisissez une valeur.")
            else:
                _event(P, fichier, "CORRIGE", ligne=lk, col=col, valeur=new.strip(),
                       valeur_precedente=None if is_blank(cell["value"]) else str(cell["value"]))
                _after(m, lk, col, suivante)
        if cell["open"] and not cell["bloq"] and st.button("Confirmer la lecture", key=f"conf_{k}", **_W(),
                                      help="La pièce dit bien cela : l'écart est accepté (tracé)."):
            _event(P, fichier, "CONFIRME", ligne=lk, col=col, valeur_vue=str(cell["value"]))
            _after(m, lk, col, suivante)
        if cell["edit"] is not None and st.button("Annuler ma modification", key=f"undo_{k}", **_W()):
            _event(P, fichier, "ANNULE", ligne=lk, col=col)
            st.rerun()
        if lg.ref and x["ref"] != col and col in lg.sources:
            if st.button(f"Prendre {mx.COL_LABEL[col]} comme source de référence pour « {lg.label} »",
                         key=f"src_{k}"):
                _event(P, fichier, "SOURCE", ligne=lk, col=col)
                st.rerun()

    opens = [(r["ligne"].key, c) for r in m["rows"] for c in mx.COLS
             if r["cells"][c]["open"] and (r["ligne"].key, c) != (lk, col)]
    if opens and st.button("Case suivante en anomalie →", key=f"next_{fichier}_{lk}_{col}"):
        st.session_state["dom_cell_force"] = opens[0]
        st.rerun()


def _cell_page(P, m, cell, col):
    fichier = m["fichier"]
    k = f"{fichier}|{cell['ligne']}|{col}"
    if col == "CARTHAGO":
        car = m["carthago"]
        if car:
            st.dataframe(pd.DataFrame([(a, b) for a, b in car.items() if not is_blank(b)],
                                      columns=["Carthago", "Valeur"]), hide_index=True, **_W())
        else:
            st.info("Aucune ligne Carthago rapprochée pour ce dossier.")
        return
    page = cell["page"] or {"DOM": 1, "CTR": 2, "CTS": 3, "TTR": 4}.get(col, 1)
    pdf = find_pdf(P.dom_in, fichier)
    if pdf is None:
        st.info(f"PDF « {fichier} » introuvable dans {P.dom_in}.")
        return
    npg = max(page_count(pdf), 1)
    z1, z2 = st.columns(2)
    pg = z1.number_input(f"Page (1–{npg})", 1, npg, min(int(page), npg), key=f"pg_{k}")
    zoom = z2.select_slider("Zoom", [1.0, 1.4, 1.8, 2.4], value=1.4, key=f"zoom_{k}")
    rot = mx.page_rotation(P.raw_json_dir, fichier, int(pg))
    png = render_page(pdf, int(pg), zoom=zoom, rotate=rot)
    if png:
        st.image(png, caption=f"{fichier} — page {pg}" + (f" (redressée de {rot}°)" if rot else ""), **_W())


def _back():
    st.session_state.pop("dom_sel", None)
    st.session_state.pop("dom_cell", None)
    st.session_state["dom_nonce"] = st.session_state.get("dom_nonce", 0) + 1  # vide la sélection de la liste


def render_detail(P, ms: list[dict]):
    fichier = st.session_state.get("dom_sel")
    m = next((x for x in ms if x["fichier"] == fichier), None)
    if m is None:
        st.session_state.pop("dom_sel", None)
        st.rerun()
    s = mx.summary(m)
    order = st.session_state.get("dom_order") or [x["fichier"] for x in ms]
    pos = order.index(fichier) if fichier in order else 0

    t = st.columns([1.2, 4, 1.2])
    if t[0].button("← Liste des dossiers"):
        _back()
        st.rerun()
    if t[2].button("Dossier suivant →", disabled=len(order) < 2):
        st.session_state["dom_sel"] = order[(pos + 1) % len(order)]
        st.session_state.pop("dom_cell", None)
        st.rerun()
    t[1].caption(f"Dossier {pos + 1} sur {len(order)} · {fichier}")

    st.subheader(s["NOM"] or fichier)
    chips = [f"Client **{s['IDENTIFIANT_CLIENT'] or '—'}**", f"Compte {s['COMPTE'] or '—'}", s["TYPE"],
             f"Fiabilité **{s['FIABILITE'] if s['FIABILITE'] is not None else '—'}**",
             f"Cases à revoir **{s['A_REVOIR']}**", f"Carthago **{s['CARTHAGO']}**", f"Statut **{s['STATUT']}**"]
    st.markdown(" · ".join(chips))

    df, sty = _matrix_frame(m)
    cfg = {"_index": st.column_config.Column("Donnée de référence", width=185),
           "Retenu (Planning)": st.column_config.Column(width=150,
                                                        help="Valeur de la source de référence (◆) envoyée au Planning"),
           "Cohérence": st.column_config.Column(width=110)}
    cfg.update({lab: st.column_config.Column(width=138) for lab in mx.COL_LABEL.values()})
    ev = st.dataframe(sty, on_select="rerun", selection_mode="single-cell", key=f"mx_{fichier}",
                      height=42 + 35 * len(df), column_config=cfg, **_W())
    opens = [(x["ligne"].key, c) for x in m["rows"] for c in mx.COLS if x["cells"][c]["open"]]
    c1, c2 = st.columns([4, 2])
    c1.caption("◆ source de référence de la ligne · texte rouge : anomalie · italique ✎ : corrigé · "
               "✓ : lecture confirmée · — : absent de la pièce · *à extraire* : pas encore lu par la Partie 1 · ⚑ vigilance. "
               "**Cliquez sur une case** pour l'ouvrir avec la page du PDF.")
    if opens and c2.button(f"Ouvrir la prochaine anomalie ({len(opens)})", key=f"nxt_{fichier}"):
        st.session_state["dom_cell_force"] = opens[0]
    cells = ev.selection.cells if ev and ev.selection else []
    if not cells:
        st.session_state.pop("dom_cell_last", None)  # un nouveau clic sur la même case la rouvrira
    want = st.session_state.pop("dom_cell_force", None)
    if want is None and cells:
        r_i, c_name = cells[0]
        lk = m["rows"][r_i]["ligne"].key
        col = next((c for c, lab in mx.COL_LABEL.items() if lab == c_name), None)
        if col is None or m["rows"][r_i]["ligne"].sources.get(col) is None:
            col = m["rows"][r_i]["ref"] or next(iter(m["rows"][r_i]["ligne"].sources))
        sel = (fichier, lk, col, tuple(cells[0]))
        if st.session_state.get("dom_cell_last") != sel:  # nouvelle case cliquée
            st.session_state["dom_cell_last"] = sel
            want = (lk, col)
    if want:
        _cell_dialog(P, m, *want)
    with st.expander("Sources de référence de ce dossier"):
        st.caption("Par défaut : paramètre de l'onglet ⑤. Un changement ici ne vaut que pour ce dossier et est tracé.")
        for x in m["rows"]:
            lg = x["ligne"]
            if not lg.ref or len(lg.sources) < 2 or m["decision"] is not None:
                continue
            opts = list(lg.sources)
            ch = st.selectbox(lg.label, opts, index=opts.index(x["ref"]) if x["ref"] in opts else 0,
                              format_func=lambda c: mx.COL_LABEL[c], key=f"srcsel_{fichier}_{lg.key}")
            if ch != x["ref"]:
                _event(P, fichier, "SOURCE", ligne=lg.key, col=ch)
                st.rerun()

    st.divider()
    dec = m["decision"]
    if dec:
        st.info(f"{'Validé' if dec['action'] == 'VALIDE' else 'Rejeté'} par {dec.get('user')} le "
                f"{dec.get('ts', '')[:16].replace('T', ' ')}"
                + (f" — motif : {dec.get('motif')}" if dec.get("motif") else "")
                + (f" — {dec.get('commentaire')}" if dec.get("commentaire") else ""))
        if st.button("Rouvrir le dossier"):
            _event(P, fichier, "ROUVERT")
            st.rerun()
        return
    a = st.columns([1.3, 2.2, 2.2, 1.3])
    if a[0].button("✔ Valider le dossier", type="primary", disabled=m["n_open"] > 0,
                   help="Possible quand toutes les cases rouges sont corrigées ou confirmées."):
        _event(P, fichier, "VALIDE", n_corrections=sum(1 for x in m["rows"] for c in x["cells"].values()
                                                       if c["edit"] is not None))
        nxt = order[(pos + 1) % len(order)] if len(order) > 1 else None
        if nxt is None:
            _back()
        else:
            st.session_state["dom_sel"] = nxt
            st.session_state.pop("dom_cell", None)
        st.rerun()
    if m["n_bloq"]:
        a[0].caption(f"{m['n_bloq']} anomalie(s) bloquante(s) : corriger ou rejeter.")
    elif m["n_open"]:
        a[0].caption(f"Encore {m['n_open']} anomalie(s) à traiter.")
    motif = a[1].selectbox("Motif client", mx.MOTIFS_REJET, key=f"motif_{fichier}")
    com = a[2].text_input("Commentaire", key=f"com_{fichier}")
    if a[3].button("Rejeter", key=f"rej_{fichier}"):
        if motif.startswith("Autre") and not com.strip():
            st.warning("Précisez le motif dans le commentaire.")
        else:
            _event(P, fichier, "REJETE", motif=motif, commentaire=com.strip() or None)
            st.rerun()


def render(P):
    lot, ms = load(P)
    if lot.fields.empty:
        st.warning("Détail des champs (CHAMPS_DETAIL) absent : la matrice affiche les valeurs consolidées "
                   "sans page ni confiance. Relancez la Partie 2.")
    if st.session_state.get("dom_sel"):
        render_detail(P, ms)
    else:
        render_list(P, ms)
