"""Écran Vigilance (page Transferts OV) : préparer le lot, lire les retours, décider sur les HIT."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from . import transfers
from . import vigilance as vg
from .common import audit, backup, current_user, is_blank, to_excel_bytes


def _W():
    from .ui import W
    return W


def _parents_lookup(P, PL: pd.DataFrame):
    """père / mère retenus dans la matrice DOM du dossier rattaché au TL (via PERIODE_ID du Planning)."""
    try:
        from . import matrice as mx
        lot = mx.load_lot(P)
        state = mx.fold(mx.read_journal(P.dom_journal))
        sources = mx.default_sources(P.sources_reference_xlsx)
    except Exception:  # noqa: BLE001  (pas de données DOM : vigilance sans les parents)
        return None
    src_of = dict(zip(PL["PERIODE_ID"], PL["FICHIER_SOURCE"])) if not PL.empty and "FICHIER_SOURCE" in PL else {}
    cache: dict = {}

    def parents(sy_row: dict) -> list[str]:
        f = src_of.get(sy_row.get("PERIODE_ID"))
        if not f:
            return []
        if f not in cache:
            try:
                m = mx.build(lot, f, state.get(f), sources)
                ret = {x["ligne"].key: x["retenu"] for x in m["rows"]}
                cache[f] = [ret.get("pere"), ret.get("mere")]
            except Exception:  # noqa: BLE001
                cache[f] = []
        return cache[f]
    return parents


def _statut_frame(sy: pd.DataFrame, st_map: dict) -> pd.DataFrame:
    rows = []
    for _, r in sy.iterrows():
        v = st_map.get(r["FICHIER"]) or {}
        rows.append({"Statut": vg.LIBELLE_STATUT.get(v.get("statut")), "Client": r.get("NOM"),
                     "Bénéficiaire": r.get("BENEFICIAIRE"), "Période": r.get("PERIODE_TL"),
                     "Montant": r.get("MONTANT_OV"), "Lot": v.get("lot"), "Motif": v.get("motif"),
                     "Fichier": r["FICHIER"]})
    return pd.DataFrame(rows)


def render(P, s, A: pd.DataFrame, SY: pd.DataFrame, PL: pd.DataFrame):
    jp = vg.journal_path(P)
    journal = vg.read_journal(jp)
    st_map = vg.statuses(journal)
    dec = transfers.load_decisions(P.decisions_csv)
    valides = set(dec[dec["DECISION"] == "VALIDE"]["FICHIER"]) if not dec.empty else set()
    sy_val = SY[SY["FICHIER"].isin(valides)]

    # ---------- indicateurs
    cnt = pd.Series([(st_map.get(f) or {}).get("statut") for f in sy_val["FICHIER"]], dtype=object)
    c = st.columns(5)
    c[0].metric("TL validés", len(sy_val))
    c[1].metric("À soumettre", int(cnt.isna().sum() + (cnt == "KO_A_REFAIRE").sum()))
    c[2].metric("Retour attendu", int((cnt == "EN_ATTENTE").sum()))
    c[3].metric("HIT / à vérifier", int(cnt.isin(list(vg.STATUTS_A_DECIDER)).sum()))
    c[4].metric("Prêts pour le registre", int(cnt.isin(list(vg.STATUTS_OK)).sum()))

    t_mod, t_prep, t_ret, t_dec, t_suivi = st.tabs(
        ["Modèle", "1 · Préparer le lot", "2 · Lire les retours", "3 · HIT à décider", "Suivi par TL"])

    # ---------- modèle
    with t_mod:
        tpl = P.vigilance_template
        st.caption("Modèle BNP « CHECK LIST TRANSFERT LIBRE » vierge (avant vigilance). Les cases sont repérées par "
                   "leur libellé en colonne A : le modèle peut évoluer sans modification de l'app.")
        if tpl.exists():
            issues = vg.check_template(tpl)
            (st.error if issues else st.success)(" · ".join(issues) if issues else f"Modèle reconnu : `{tpl.name}`")
        else:
            st.warning("Aucun modèle chargé.")
        up = st.file_uploader("Charger le modèle avant vigilance (.xlsx)", type=["xlsx"], key="vig_tpl")
        if up and st.button("Enregistrer le modèle", key="vig_tpl_save"):
            tmp = tpl.with_suffix(".tmp.xlsx")
            tpl.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(up.getbuffer())
            issues = vg.check_template(tmp)
            if issues:
                tmp.unlink()
                st.error("Modèle refusé : " + " · ".join(issues))
            else:
                backup(tpl)
                tmp.replace(tpl)
                audit(P.audit_log, "VIGILANCE_MODELE", current_user(), fichier=up.name)
                st.success("Modèle enregistré.")
                st.rerun()

    # ---------- 1. préparer
    with t_prep:
        cand = vg.candidates(dec, st_map)
        cand = [f for f in cand if f in set(SY["FICHIER"])]
        st.caption("TL validés jamais soumis, ou à refaire (plateforme indisponible). Un fichier par client si le "
                   "bénéficiaire est le même sur ses TL, sinon un fichier par bénéficiaire (nom + IBAN + SWIFT).")
        if not cand:
            st.info("Aucun TL validé en attente de vigilance.")
        elif not P.vigilance_template.exists():
            st.warning("Chargez d'abord le modèle (onglet Modèle).")
        else:
            ds = vg.dossiers_from_ov(SY, A, cand, _parents_lookup(P, PL), s.vigilance_individus)
            units = vg.build_units(ds)
            st.dataframe(pd.DataFrame([{
                "Réf dossier": u["ref"], "Client": u["client"], "Bénéficiaire": u["beneficiaire"] or "(le client)",
                "Banque": u["banque"], "Pays banque": u["pays_banque"], "Divers individus": " / ".join(u["individus"]),
                "TL": len(u["fichiers"]), "Fichier": u["fichier"]} for u in units]), hide_index=True, **_W())
            manq = [u["ref"] for u in units if not u["banque"] or not u["pays_banque"]]
            if manq:
                st.warning(f"Banque ou pays non lu pour : {', '.join(manq)} — corrigez l'OV avant l'envoi si nécessaire.")
            st.caption(f"Lieu de travail : **{s.employeur_raison_sociale}** · {len(units)} fichier(s) pour {len(cand)} TL.")
            if st.button(f"Préparer {len(units)} check-list(s)", type="primary", key="vig_prep"):
                m = vg.prepare(units, P.vigilance_template, P.vigilance_dir / "envois" / "en_cours",
                               s.employeur_raison_sociale)
                dest = P.vigilance_dir / "envois" / m["lot"]
                (P.vigilance_dir / "envois" / "en_cours").rename(dest)
                vg.append(jp, current_user(), "ENVOI", lot=m["lot"], unites=units)
                audit(P.audit_log, "VIGILANCE_ENVOI", current_user(), lot=m["lot"], unites=len(units), tl=len(cand))
                st.session_state["vig_last_lot"] = str(dest)
                st.rerun()
        last = st.session_state.get("vig_last_lot")
        lots = sorted((P.vigilance_dir / "envois").glob("VIG_*"), reverse=True) if (P.vigilance_dir / "envois").exists() else []
        if lots:
            st.divider()
            pick = st.selectbox("Lots préparés", lots, format_func=lambda p: p.name,
                                index=next((i for i, p in enumerate(lots) if str(p) == last), 0), key="vig_lot_pick")
            z = next(pick.glob("*_a_deposer.zip"), None)
            r = next(pick.glob("*_recapitulatif.xlsx"), None)
            cc = st.columns(2)
            if z:
                cc[0].download_button("⬇ Check-lists à déposer (ZIP)", z.read_bytes(), file_name=z.name, type="primary")
            if r:
                cc[1].download_button("⬇ Récapitulatif (Excel)", r.read_bytes(), file_name=r.name)

    # ---------- 2. retours
    with t_ret:
        st.caption("Déposez les fichiers « Recherche_Vigilance_Data_… » reçus (plusieurs .xlsx ou un ZIP). Chaque retour "
                   "est rattaché à son envoi (identifiant dans le nom, sinon réf dossier + bénéficiaire + banque).")
        ups = st.file_uploader("Retours de vigilance", type=["xlsx", "zip"], accept_multiple_files=True, key="vig_ret")
        if ups and st.button("Lire les retours", type="primary", key="vig_read"):
            try:
                res = vg.import_returns([(u.name, bytes(u.getbuffer())) for u in ups], journal, jp, current_user(),
                                        P.vigilance_dir / "retours")
                audit(P.audit_log, "VIGILANCE_RETOUR", current_user(), fichiers=len(ups), unites=len(res["synthese"]))
                st.session_state["vig_res"] = str(res["classeur"])
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Lecture impossible : {exc}")
        if st.session_state.get("vig_res") and Path(st.session_state["vig_res"]).exists():
            path = Path(st.session_state["vig_res"])
            sy_r = pd.read_excel(path, sheet_name="Synthese")
            co = pd.read_excel(path, sheet_name="Controles")
            st.markdown(f"**Dernière lecture** — `{path.name}`")
            st.dataframe(sy_r.drop(columns=["UID"], errors="ignore"), hide_index=True, **_W())
            if not co.empty:
                st.warning(f"{len(co)} contrôle(s) de structure à examiner")
                st.dataframe(co, hide_index=True, **_W())
            st.download_button("⬇ Résultats détaillés (Excel)", path.read_bytes(), file_name=path.name)

    # ---------- 3. décisions
    with t_dec:
        a_dec = [f for f in sy_val["FICHIER"] if (st_map.get(f) or {}).get("statut") in vg.STATUTS_A_DECIDER]
        if not a_dec:
            st.success("Aucun HIT ni résultat à vérifier en attente de décision.")
        units = {}
        for f in a_dec:
            units.setdefault(st_map[f]["uid"], []).append(f)
        last_ret = {ev["uid"]: ev for ev in journal if ev.get("action") == "RETOUR"}
        for uid, fs in units.items():
            ev = last_ret.get(uid, {})
            r0 = SY[SY["FICHIER"] == fs[0]].iloc[0]
            with st.container(border=True):
                stat = st_map[fs[0]]["statut"]
                st.markdown(f"**{'🔴 HIT' if stat == 'HIT' else '🟠 À vérifier'} — {r0.get('NOM')}** · bénéficiaire "
                            f"{r0.get('BENEFICIAIRE') or '—'} · {len(fs)} TL")
                hits = ev.get("hits") or []
                if hits:
                    st.dataframe(pd.DataFrame(hits, columns=["Rubrique", "Rang", "Valeur", "Résultat", "Statut",
                                                             "Action", "Commentaire"]), hide_index=True, **_W())
                for x in ev.get("controles") or []:
                    st.caption(f"⚠ {x}")
                st.caption("TL : " + ", ".join(fs))
                motif = st.text_area("Motif (obligatoire)", key=f"vig_m_{uid}", height=70)
                b1, b2 = st.columns(2)
                if b1.button("Lever l'alerte — le TL peut continuer", key=f"vig_l_{uid}"):
                    try:
                        vg.decide(jp, current_user(), fs, "LEVEE", motif, uid)
                        audit(P.audit_log, "VIGILANCE_LEVEE", current_user(), uid=uid, tl=fs, motif=motif)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                if b2.button("Confirmer l'alerte — rejeter le(s) TL", key=f"vig_c_{uid}", type="primary"):
                    try:
                        vg.decide(jp, current_user(), fs, "CONFIRMEE", motif, uid)
                        ed = pd.DataFrame([{"FICHIER": f, "AUDIT_SOURCE": None, "DECISION": "REJETE",
                                            "COMMENTAIRE": f"Vigilance HIT confirmé : {motif.strip()}"} for f in fs])
                        transfers.save_decisions(P.decisions_csv, ed, current_user())
                        audit(P.audit_log, "VIGILANCE_CONFIRMEE", current_user(), uid=uid, tl=fs, motif=motif)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    # ---------- suivi
    with t_suivi:
        df = _statut_frame(sy_val, st_map)
        if df.empty:
            st.info("Aucun TL validé dans ce lot d'extraction.")
        else:
            st.dataframe(df, hide_index=True, **_W(), height=380,
                         column_config={"Montant": st.column_config.NumberColumn(format="%.2f")})
            st.download_button("⬇ Suivi vigilance (Excel)", to_excel_bytes({"VIGILANCE": df}),
                               file_name="suivi_vigilance.xlsx")


def statut_map(P) -> dict[str, str]:
    """{fichier: statut} pour le registre."""
    return {f: v["statut"] for f, v in vg.statuses(vg.read_journal(vg.journal_path(P))).items()
            if not is_blank(v.get("statut"))}
