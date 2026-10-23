"""Écran de validation des transferts : liste des dossiers OV (jusqu'à ~1000) → matrice → page du PDF."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from . import ov_matrice as ov
from . import transfers
from .common import audit, current_user, find_pdf, is_blank, page_count, render_page

RED, GREY = "#B3261E", "#6B7470"
FEU = {"r": "🔴 Non conforme", "o": "🟠 À revoir", "v": "🟢 Conforme"}
FILTRES = ["À traiter", "Conformes non décidés", "Décidés", "Tous"]


def _W():
    from .ui import W
    return W


def _mt(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


def journal_path(P) -> Path:
    return P.tr_root / "journal_validation_ov.jsonl"


@st.cache_resource(show_spinner="Contrôles des transferts…", max_entries=4)
def _base(_P, _s, audit_path: str, key: tuple, _hist: dict | None = None):
    """Lecture du lot + contrôles sur les valeurs extraites (mis en cache : ~12 s pour 1000 dossiers).
    Le registre utilisé par les contrôles (T14 période déjà transférée, T15 cumul DOM) inclut les TL réellement
    exécutés d'après l'historique Atlas (page 4), y compris ceux antérieurs à TL-One."""
    from . import execution
    from .planning import load_planning
    a = transfers.read_audit_xlsx(Path(audit_path))
    pl = load_planning(_P.planning_csv)
    h = _hist or {}
    hreg = execution.registre_atlas(pl, h.get("trade"), h.get("atlas"))
    from . import referentiels
    R = referentiels.load_all(_P)
    refs = (execution.registre_complet(transfers.load_registre(_P.registre_csv), hreg, _s.tolerance_montant_dzd),
            R["atf"], R["aut"], R["rh"])
    sy, ch = transfers.control_each(a, pl, *refs[:3], _s, rh=R["rh"])
    return a, sy, ch, pl, refs


@st.cache_data(show_spinner=False, max_entries=8)
def _rh_df(_P, sig: tuple):
    from . import referentiels
    return referentiels.load_rh(_P)


def rh_row(P, sy: dict) -> dict | None:
    """Ligne de la base RH du dossier (même client / mois / part) pour la colonne « Base RH » de la matrice."""
    from . import referentiels, rh
    df = _rh_df(P, referentiels.signature(P))
    per = str(sy.get("PERIODE_TL") or "")
    r, _ = rh.match(df, sy.get("SIEGE_RACINE"), per[:7] or None, per[7:] or None, sy.get("NOM"))
    if r:
        att = sy.get("RH_PART_TRANSFERABLE")      # base RH du mois entier : part attendue de la période (quote-part)
        r = dict(r, PART_TRANSFERABLE=att if att is not None else r.get("PART_TRANSFERABLE"))
    return r


def load(P, s, src: Path):
    """Contrôles du lot, recalculés seulement pour les dossiers corrigés par un valideur."""
    from . import referentiels
    key = (_mt(src), _mt(P.planning_csv), _mt(P.registre_csv), str(P.data_root)) + referentiels.signature(P)
    from .ui import historique_data
    _f, hist, _r, _e, hkey = historique_data(P, s)
    a, sy, ch, pl, (reg, atf, aut, rhdf) = _base(P, s, str(src), key + hkey, hist)
    journal = ov.read_journal(journal_path(P))
    fixed = set(ov.fold_ov(journal)) & set(a["fichier"].astype(str))
    if fixed:
        a = ov.apply_corrections(a, journal)
        sub = a[a["fichier"].astype(str).isin(fixed)]
        sy2, ch2 = transfers.control_each(sub, pl, reg, atf, aut, s, rh=rhdf)
        sy = pd.concat([sy[~sy["FICHIER"].isin(fixed)], sy2]).set_index("FICHIER").loc[list(sy["FICHIER"])].reset_index()
        ch = pd.concat([ch[~ch["FICHIER"].isin(fixed)], ch2], ignore_index=True)
    sy, ch = transfers.mark_lot_duplicates(sy, ch)
    return a, sy, ch, pl


def _decide(P, sy_row: dict, decision: str, commentaire: str):
    ed = pd.DataFrame([{"FICHIER": sy_row["FICHIER"], "AUDIT_SOURCE": sy_row.get("AUDIT_SOURCE"),
                        "STATUT_CONTROLE": sy_row.get("STATUT_CONTROLE"), "PERIODE_ID": sy_row.get("PERIODE_ID"),
                        "DECISION": decision, "COMMENTAIRE": commentaire}])
    errs = transfers.check_decisions(ed)
    if errs:
        return errs
    transfers.save_decisions(P.decisions_csv, ed, current_user())
    audit(P.audit_log, f"TL_{decision}", current_user(), fichier=sy_row["FICHIER"], commentaire=commentaire)
    return []


# ----------------------------------------------------------------------------- complétude du lot
def completude(P, A: pd.DataFrame) -> pd.DataFrame:
    """PDF déposés dans transferts_in absents du lot affiché, avec la raison probable."""
    import re
    pdfs = sorted(q for q in P.tr_in.iterdir() if q.is_file() and q.suffix.lower() == ".pdf") if P.tr_in.exists() else []
    lot = {Path(str(x)).stem for x in (A["fichier"] if "fichier" in A else [])}
    manq = [q for q in pdfs if q.stem not in lot]
    if not manq:
        return pd.DataFrame()
    errs = {}
    log = P.tr_out / "pipeline.log"
    if log.exists():
        for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]:
            m = re.search(r"❌\s+(.+?\.pdf)\s+—\s+(.*)$", ln, re.I)
            if m:
                errs[Path(m[1]).stem] = (ln[:19], m[2])
            m = re.search(r"✅\s+(.+?\.pdf)\b", ln, re.I)
            if m:
                errs.pop(Path(m[1]).stem, None)
    jdirs = [q for q in P.tr_out.glob("json_dossiers*") if q.is_dir()] if P.tr_out.exists() else []
    rows = []
    for q in manq:
        if q.stem in errs:
            raison = f"Erreur d'extraction le {errs[q.stem][0]} : {errs[q.stem][1]}"
        elif any((j / f"{q.stem}.json").exists() for j in jdirs):
            raison = "Extrait (JSON présent) mais absent de ce classeur : sélectionner le lot le plus récent ou relancer"
        else:
            raison = ("Pas encore extrait : lancer l'extraction (avec « Limiter à N », seuls les N premiers PDF "
                      "non encore extraits sont lus)")
        rows.append({"PDF": q.name, "Déposé le": pd.Timestamp(q.stat().st_mtime, unit="s").strftime("%d/%m/%Y %H:%M"),
                     "Raison": raison})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- liste
def render_list(P, s, src: Path, A, SY, CH):
    dec = transfers.load_decisions(P.decisions_csv)
    df = ov.list_frame(SY, dec)
    if df.empty:
        st.info("Aucun dossier dans ce lot.")
        return
    rank = {"r": 0, "o": 1, "v": 2}
    df["_k"] = [(1 if d else 0, rank[f]) for d, f in zip(df["DECISION"], df["FEU"])]
    df = df.sort_values("_k", kind="stable").drop(columns="_k").reset_index(drop=True)
    decided = df["DECISION"].isin(["VALIDE", "REJETE"])

    c = st.columns(6)
    c[0].metric("Dossiers", len(df))
    c[1].metric("Non conformes", int((df["STATUT_CONTROLE"] == "NON_CONFORME").sum()))
    c[2].metric("À revoir", int((df["STATUT_CONTROLE"] == "A_REVOIR").sum()))
    c[3].metric("Conformes", int((df["STATUT_CONTROLE"] == "CONFORME").sum()))
    c[4].metric("Validés", int((df["DECISION"] == "VALIDE").sum()))
    c[5].metric("Rejetés", int((df["DECISION"] == "REJETE").sum()))

    # ---- validation en masse des conformes, après contrôle visuel d'un échantillon
    conf = df[(df["STATUT_CONTROLE"] == "CONFORME") & ~decided & df["RATTACHE"]]
    with st.expander(f"Validation en masse des dossiers conformes ({len(conf)} non décidés)", expanded=False):
        ech = ov.sample(list(conf["FICHIER"]) + list(df[(df["STATUT_CONTROLE"] == "CONFORME") &
                                                       (df["DECISION"] == "VALIDE")]["FICHIER"]), seed=src.name)
        faits = set(df[df["DECISION"] == "VALIDE"]["FICHIER"])
        reste = [f for f in ech if f not in faits]
        st.caption(f"Avant de valider en masse, un échantillon de {len(ech)} dossier(s) conforme(s) tiré au sort doit "
                   "être ouvert et validé un par un (contrôle visuel). Tirage reproductible pour ce lot.")
        st.dataframe(pd.DataFrame({"Échantillon": ech, "Contrôlé": ["✓" if f in faits else "à faire" for f in ech]}),
                     hide_index=True, **_W())
        ok = st.checkbox(f"Je confirme valider {len(conf)} dossier(s) conforme(s) sans les ouvrir un par un",
                         disabled=bool(reste) or conf.empty, key="ov_bulk_ok")
        if st.button("Valider en masse", type="primary", disabled=bool(reste) or conf.empty or not ok):
            com = f"Validation en masse — échantillon contrôlé : {', '.join(ech)}"
            sy = SY.set_index("FICHIER")
            ed = pd.DataFrame([{"FICHIER": f, "AUDIT_SOURCE": sy.loc[f, "AUDIT_SOURCE"],
                                "STATUT_CONTROLE": "CONFORME", "PERIODE_ID": sy.loc[f, "PERIODE_ID"],
                                "DECISION": "VALIDE", "COMMENTAIRE": com} for f in conf["FICHIER"]])
            n = transfers.save_decisions(P.decisions_csv, ed, current_user())
            audit(P.audit_log, "TL_VALIDATION_MASSE", current_user(), n=n, lot=src.name, echantillon=ech)
            st.success(f"{n} dossier(s) validé(s).")
            st.rerun()
        if reste:
            st.caption(f"Reste à contrôler : {', '.join(reste)}")

    f1, f2, f3 = st.columns([3, 2, 2])
    nb = {"À traiter": int((~decided & (df["STATUT_CONTROLE"] != "CONFORME")).sum()),
          "Conformes non décidés": int((~decided & (df["STATUT_CONTROLE"] == "CONFORME")).sum()),
          "Décidés": int(decided.sum()), "Tous": len(df)}
    filt = f1.segmented_control("Afficher", FILTRES, default="À traiter", key="ov_filtre",
                                format_func=lambda x: f"{x} ({nb[x]})") or "Tous"
    q = f2.text_input("Rechercher", placeholder="Nom, identifiant client ou fichier", key="ov_q")
    per = f3.selectbox("Lignes par page", [50, 100, 250, 1000], index=1, key="ov_per")
    view = df
    if filt == "À traiter":
        view = df[~decided & (df["STATUT_CONTROLE"] != "CONFORME")]
    elif filt == "Conformes non décidés":
        view = df[~decided & (df["STATUT_CONTROLE"] == "CONFORME")]
    elif filt == "Décidés":
        view = df[decided]
    if q:
        ql = q.strip().lower()
        view = view[view[["NOM", "IDENTIFIANT_CLIENT", "FICHIER"]].fillna("").astype(str)
                    .apply(lambda r: ql in " ".join(r).lower(), axis=1)]
    if view.empty:
        st.caption("Aucun dossier pour ce filtre.")
        return
    npages = max(1, -(-len(view) // per))
    page = st.number_input(f"Page (1–{npages})", 1, npages, 1, key="ov_page") if npages > 1 else 1
    view = view.iloc[(page - 1) * per: page * per]
    show = pd.DataFrame({
        "État": view["FEU"].map(FEU), "Client": view["NOM"], "Identifiant client": view["IDENTIFIANT_CLIENT"],
        "Période": view["PERIODE"], "Montant OV": view["MONTANT"], "Plafond retenu": view["PLAFOND"],
        "Limitant": view["LIMITANT"], "Marge": view["MARGE"], "Bloquants": view["BLOQUANTS"],
        "À revoir": view["A_REVOIR"], "Décision": view["DECISION"], "Fichier": view["FICHIER"],
    }).reset_index(drop=True)

    def color(col):
        out = []
        for v in col:
            bad = False
            if col.name in ("Bloquants", "À revoir"):
                bad = v > 0
            elif col.name == "Marge":
                bad = v is not None and not pd.isna(v) and float(v) < 0
            elif col.name == "Période":
                bad = is_blank(v)
            out.append(f"color: {RED}; font-weight: 600" if bad else "")
        return out
    num = {c: st.column_config.NumberColumn(format="%.2f") for c in ("Montant OV", "Plafond retenu", "Marge")}
    ev = st.dataframe(show.style.apply(color, axis=0), hide_index=True, on_select="rerun",
                      selection_mode="single-row", key=f"ov_list_{st.session_state.get('ov_nonce', 0)}_{page}",
                      height=min(42 + 35 * len(show), 700), column_config=num, **_W())
    st.caption("Cliquez sur une ligne pour ouvrir le dossier. Texte rouge = anomalie.")
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        st.session_state["ov_sel"] = show.loc[sel[0], "Fichier"]
        st.session_state["ov_order"] = list(view["FICHIER"])
        st.rerun()


# ----------------------------------------------------------------------------- détail
def _frame(m):
    labels, data, styles = [], [], []
    for x in m["rows"]:
        lg = x["ligne"]
        line, sty = {}, {}
        for c in ov.COLS:
            cell, lab = x["cells"][c], ov.COL_LABEL[c]
            if not cell["present"]:
                line[lab], sty[lab] = "", ""
                continue
            txt = cell["text"] if cell["text"] is not None else "—"
            if cell["edit"] is not None:
                txt += " ✎"
            if c == x["ref"]:
                txt = "◆ " + txt
            line[lab] = txt
            css = [f"color: {RED}; font-weight: 600"] if cell["open"] else ([f"color: {GREY}"] if txt == "—" else [])
            if cell["edit"] is not None:
                css.append("font-style: italic")
            sty[lab] = "; ".join(css)
        line["Retenu"] = x["retenu_txt"] or ""
        sty["Retenu"] = "font-weight: 600"
        line["Cohérence"] = x["coh"]
        sty["Cohérence"] = f"color: {RED}; font-weight: 600" if x["n_open"] else ""
        labels.append(lg.label)
        data.append(line)
        styles.append(sty)
    df = pd.DataFrame(data, index=labels)
    sdf = pd.DataFrame(styles, index=labels)
    return df, df.style.apply(lambda _: sdf, axis=None)


@st.dialog("Vérification de la case", width="large")
def _dialog(P, m, A, lk, col, decided):
    x = next(r for r in m["rows"] if r["ligne"].key == lk)
    lg, cell = x["ligne"], x["cells"][col]
    f = m["fichier"]
    st.markdown(f"### {lg.label} · {ov.COL_LABEL[col]}")
    g, d = st.columns([2, 3], gap="medium")
    with g:
        info = [("Valeur lue", cell["value"]), ("Valeur retenue", x["retenu_txt"]),
                ("Champ extrait", cell["src"] if cell["src"] and not cell["src"].startswith(("SY:", "PL:")) else None),
                ("Contrôles", ", ".join(lg.controls))]
        st.dataframe(pd.DataFrame([(k, "" if is_blank(v) else str(v)) for k, v in info], columns=["", "Valeur"]),
                     hide_index=True, **_W())
        for kind, msg in cell["issues"]:
            st.error({"bloq": "Bloquant : ", "incoh": "Anomalie : "}.get(kind, "À vérifier : ") + msg)
        if cell["edit"] is not None:
            e = cell["edit"]
            st.caption(f"Corrigé par {e.get('user')} le {e.get('ts', '')[:16].replace('T', ' ')} "
                       f"(lu : {e.get('valeur_precedente') or '—'})")
        if col in ov.EXTRACTED and not decided and cell["src"] and not cell["src"].startswith(("SY:", "PL:")):
            new = st.text_input("Corriger la valeur lue", value="" if is_blank(cell["value"]) else str(cell["value"]),
                                key=f"ovc_{f}_{lk}_{col}")
            st.caption("Les contrôles T01–T17 sont recalculés sur la valeur corrigée.")
            if st.button("Enregistrer la correction", type="primary", key=f"ovs_{f}_{lk}_{col}", **_W()):
                if not is_blank(new):
                    ov.append_event(journal_path(P), current_user(), f, "CORRIGE", champ=cell["src"],
                                    valeur=new.strip(), valeur_precedente=None if is_blank(cell["value"])
                                    else str(cell["value"]))
                    audit(P.audit_log, "TL_CORRECTION", current_user(), fichier=f, champ=cell["src"], valeur=new.strip())
                    st.rerun()
            if cell["edit"] is not None and st.button("Annuler ma correction", key=f"ovu_{f}_{lk}_{col}", **_W()):
                ov.append_event(journal_path(P), current_user(), f, "ANNULE", champ=cell["src"])
                st.rerun()
        elif col not in ov.EXTRACTED:
            st.caption("Valeur issue du Planning TL ou d'un référentiel : elle se corrige à la source.")
    with d:
        pdf = find_pdf(P.tr_in, f)
        if pdf is None:
            st.info(f"PDF « {f} » introuvable dans {P.tr_in}.")
            return
        npg = max(page_count(pdf), 1)
        row = A[A["fichier"].astype(str) == f]
        lue = page_piece(row.iloc[0].get("pages_pieces") if not row.empty and "pages_pieces" in row else None, col)
        guess = lue or {"OV": 1, "ANNEXE_I": 2, "ANNEXE_II": 3, "BULLETIN": 4}.get(col, 1)
        z1, z2 = st.columns(2)
        pg = z1.number_input(f"Page (1–{npg})", 1, npg, min(guess, npg), key=f"ovpg_{f}_{lk}_{col}",
                             help="Page de la pièce mémorisée par le notebook (v29)." if lue else
                             "Page estimée (OV 1, Annexe I 2, Annexe II 3, bulletin 4) : le notebook v27/v28 "
                             "ne mémorise pas la page de chaque pièce ; v29 le fait.")
        zoom = z2.select_slider("Zoom", [1.0, 1.4, 1.8, 2.4], value=1.4, key=f"ovz_{f}_{lk}_{col}")
        png = render_page(pdf, int(pg), zoom=zoom)
        if png:
            st.image(png, caption=f"{f} — page {pg}", **_W())


def page_piece(pages_pieces, piece: str) -> int | None:
    """« OV:1, ANNEXE_I:2, ANNEXE_II:3+5 » (notebook v29) -> première page de la pièce, sinon None."""
    if pages_pieces is None or is_blank(pages_pieces):
        return None
    for part in str(pages_pieces).split(","):
        k, _, v = part.strip().partition(":")
        if k.strip() == piece:
            n = v.split("+")[0].strip()
            return int(n) if n.isdigit() else None
    return None


def _back():
    st.session_state.pop("ov_sel", None)
    st.session_state["ov_nonce"] = st.session_state.get("ov_nonce", 0) + 1


def render_detail(P, s, A, SY, CH, PL):
    f = st.session_state.get("ov_sel")
    if f not in set(SY["FICHIER"]):
        _back()
        st.rerun()
    sy = {k: (None if is_blank(v) else v) for k, v in SY[SY["FICHIER"] == f].iloc[0].to_dict().items()}
    d = A[A["fichier"].astype(str) == f].iloc[0].to_dict()
    corr = ov.fold_ov(ov.read_journal(journal_path(P))).get(f, {})
    m = ov.build_ov(f, d, sy, CH, PL, corr, s.seuil_similarite_nom, rh_row(P, sy))
    dec = transfers.load_decisions(P.decisions_csv)
    dd = dec[dec["FICHIER"] == f]
    decision = dd.iloc[-1].to_dict() if not dd.empty and not is_blank(dd.iloc[-1]["DECISION"]) else None
    order = st.session_state.get("ov_order") or list(SY["FICHIER"])
    pos = order.index(f) if f in order else 0

    t = st.columns([1.2, 4, 1.2])
    if t[0].button("← Liste des dossiers", key="ov_back"):
        _back()
        st.rerun()
    if t[2].button("Dossier suivant →", key="ov_next", disabled=len(order) < 2):
        st.session_state["ov_sel"] = order[(pos + 1) % len(order)]
        st.rerun()
    t[1].caption(f"Dossier {pos + 1} sur {len(order)} · {f}")
    st.subheader(sy.get("NOM") or f)
    fmt = lambda v: "—" if v is None else f"{float(v):,.2f}".replace(",", " ")  # noqa: E731
    st.markdown(" · ".join([f"Client **{sy.get('SIEGE_RACINE') or '—'}**", f"Période **{sy.get('PERIODE_TL') or '—'}**",
                            f"OV **{fmt(sy.get('MONTANT_OV'))}** {sy.get('DEVISE') or ''}",
                            f"Plafond **{fmt(sy.get('PLAFOND_RETENU'))}** ({sy.get('PLAFOND_LIMITANT') or '—'})",
                            f"Provision Atlas {fmt(sy.get('PROVISION_ATLAS'))}",
                            f"Contrôle **{str(sy.get('STATUT_CONTROLE')).replace('_', ' ').lower()}**"]))
    df, sty = _frame(m)
    cfg = {"_index": st.column_config.Column("Donnée", width=160), "Retenu": st.column_config.Column(width=115),
           "Cohérence": st.column_config.Column(width=90)}
    cfg.update({lab: st.column_config.Column(width=108) for lab in ov.COL_LABEL.values()})
    ev = st.dataframe(sty, on_select="rerun", selection_mode="single-cell", key=f"ovmx_{f}",
                      height=42 + 35 * len(df), column_config=cfg, **_W())
    st.caption("◆ référence de la ligne · texte rouge : anomalie · ✎ : corrigé (contrôles recalculés). "
               "Cliquez sur une case pour l'ouvrir avec la page du PDF.")
    cells = ev.selection.cells if ev and ev.selection else []
    if not cells:
        st.session_state.pop("ov_cell_last", None)
    else:
        r_i, c_name = cells[0]
        col = next((c for c, lab in ov.COL_LABEL.items() if lab == c_name), "OV")
        sel = (f, r_i, c_name)
        if st.session_state.get("ov_cell_last") != sel:
            st.session_state["ov_cell_last"] = sel
            _dialog(P, m, A, m["rows"][r_i]["ligne"].key, col, decision is not None)

    dc = m["dossier_checks"]
    if not dc.empty:
        st.markdown("**Contrôles du dossier**")
        icon = {"OK": "✓", "KO": "✗", "NON_CONTROLABLE": "?"}
        t2 = pd.DataFrame({"": dc["RESULTAT"].map(icon).fillna("·"), "Code": dc["CODE"], "Contrôle": dc["CONTROLE"],
                           "Sévérité": dc["SEVERITE"], "Détail": dc["DETAIL"]}).reset_index(drop=True)
        bad = list(dc["RESULTAT"].isin(["KO", "NON_CONTROLABLE"]))
        st.dataframe(t2.style.apply(lambda col: [f"color: {RED}; font-weight: 600" if b else "" for b in bad], axis=0),
                     hide_index=True, **_W())
    with st.expander("Tous les contrôles T01–T17"):
        st.dataframe(m["checks"].drop(columns=["FICHIER"]), hide_index=True, **_W())

    st.divider()
    if decision:
        st.info(f"{decision['DECISION']} par {decision.get('USER')} le {str(decision.get('TS') or '')[:16].replace('T', ' ')}"
                + (f" — {decision.get('COMMENTAIRE')}" if not is_blank(decision.get("COMMENTAIRE")) else ""))
        if st.button("Annuler la décision", key="ov_reopen"):
            _decide(P, sy, "", "décision annulée")
            st.rerun()
        return
    a = st.columns([1.4, 3, 1.3])
    com = a[1].text_input("Commentaire / justification", key=f"ovcom_{f}",
                          help="Obligatoire pour rejeter, ou pour valider un dossier non conforme.")
    if a[0].button("✔ Valider le TL", type="primary", key=f"ovval_{f}"):
        errs = _decide(P, sy, "VALIDE", com.strip())
        if errs:
            st.error("\n".join(errs))
        else:
            if len(order) > 1:
                st.session_state["ov_sel"] = order[(pos + 1) % len(order)]
            else:
                _back()
            st.rerun()
    if a[2].button("Rejeter", key=f"ovrej_{f}"):
        errs = _decide(P, sy, "REJETE", com.strip())
        if errs:
            st.error("\n".join(errs))
        else:
            st.rerun()


def render(P, s, src: Path):
    A, SY, CH, PL = load(P, s, src)
    if SY.empty:
        st.info("Lot vide.")
        return
    if st.session_state.get("ov_sel"):
        render_detail(P, s, A, SY, CH, PL)
    else:
        manq = completude(P, A)
        if not manq.empty:
            with st.expander(f"⚠️ {len(manq)} PDF déposé(s) absent(s) de ce lot", expanded=True):
                st.dataframe(manq, hide_index=True, **_W())
        render_list(P, s, src, A, SY, CH)
