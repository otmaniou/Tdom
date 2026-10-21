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
                     "Analysé par": v.get("decide_par"), "Fichier": r["FICHIER"],
                     "_annotee": v.get("fiche_annotee")})
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

    # ---------- 3. analyse des HIT dans TL-One
    with t_dec:
        a_dec = [f for f in sy_val["FICHIER"] if (st_map.get(f) or {}).get("statut") in vg.STATUTS_A_DECIDER]
        if not a_dec:
            st.success("Aucun HIT ni résultat à vérifier en attente d'analyse.")
        st.caption("Pour chaque alerte : avéré ou non avéré, avec un commentaire. Tous les points non avérés → le TL est "
                   "libéré. Un seul point avéré → l'alerte est confirmée et le TL rejeté. L'analyse est écrite dans la "
                   "colonne COMMENTAIRES de la fiche (fiche annotée à archiver).")
        units = {}
        for f in a_dec:
            units.setdefault(st_map[f]["uid"], []).append(f)
        last_ret = {ev["uid"]: ev for ev in journal if ev.get("action") == "RETOUR"}
        mem = vg.memoire_hits(journal)
        envoyes = vg._units_from_journal(journal)
        for uid, fs in units.items():
            ev = last_ret.get(uid, {})
            r0 = SY[SY["FICHIER"] == fs[0]].iloc[0]
            stat = st_map[fs[0]]["statut"]
            with st.container(border=True):
                st.markdown(f"#### {'🔴 HIT' if stat == 'HIT' else '🟠 À vérifier'} — {r0.get('NOM')}")
                st.caption(f"Bénéficiaire {r0.get('BENEFICIAIRE') or '—'} · {len(fs)} TL : {', '.join(fs)}")
                chemin = Path(ev["chemin"]) if ev.get("chemin") else None
                if chemin and chemin.exists():
                    fiche = vg.read_return(chemin.read_bytes())
                    rows = [{"Rubrique": rb["rubrique"], "Valeur": rb["valeur"], "Résultat": rb["resultat"],
                             "Commentaire": rb["commentaire"]} for rb in fiche["rubriques"]
                            if rb["valeur"] or vg.classify(rb["resultat"])[0] != "INFO"]
                    with st.expander("Fiche vigilance retournée", expanded=True):
                        def _red(row):
                            hit = any(vg.classify(x)[0] in ("HIT", "MANQUANT", "INCONNU")
                                      for x in (vg.lines(row["Résultat"]) or [""]))
                            return ["color: #B3261E; font-weight: 600" if hit else ""] * len(row)
                        st.dataframe(pd.DataFrame(rows).style.apply(_red, axis=1), hide_index=True, **_W())
                        st.download_button("⬇ Fiche retournée", chemin.read_bytes(), file_name=chemin.name,
                                           key=f"vig_dl_{uid}")
                for x in ev.get("controles") or []:
                    st.caption(f"⚠ {x}")
                points = ev.get("points") or ev.get("hits") or []
                ref_client = (envoyes.get(uid) or {}).get("ref_client")
                reco = vg.reconduire(mem, ref_client, points, ev.get("ts"))
                if reco:
                    st.info(f"♻️ Alerte déjà traitée : {len(reco)} point(s) analysé(s) « non avéré » lors d'un mois "
                            "précédent (même client, même rubrique, même valeur). Vous pouvez reconduire l'analyse ; "
                            "elle est tracée comme reconduction.")
                    if st.button("♻️ Reconduire l'analyse précédente et libérer le TL", key=f"vig_reco_{uid}",
                                 type="primary"):
                        evd = vg.analyse_points(jp, current_user(), uid, fs, reco, chemin, P.vigilance_dir / "analyses")
                        audit(P.audit_log, "VIGILANCE_RECONDUCTION", current_user(), uid=uid, tl=fs, motif=evd["motif"])
                        st.session_state["vig_msg"] = "Analyse reconduite : TL libéré(s)."
                        st.rerun()
                with st.form(f"vig_form_{uid}"):
                    verdicts = []
                    for i, pt in enumerate(points):
                        rub, rang, val, raw, stt = pt[0], pt[1], pt[2], pt[3], pt[4]
                        st.markdown(f"**{rub}**" + (f" — {val}" if val else "") + f" · résultat : `{raw or 'vide'}`")
                        prec = vg.precedent(mem, ref_client, rub, val, ev.get("ts"))
                        if prec:
                            st.caption(f"Déjà analysé le {str(prec['ts'])[:10]} par {prec['user']} : "
                                       f"**{vg.VERDICTS.get(prec['verdict'])}** — {prec['commentaire']}")
                        c1, c2 = st.columns([1, 2])
                        opts = list(vg.VERDICTS)
                        ver = c1.radio("Analyse", opts, format_func=vg.VERDICTS.get,
                                       index=opts.index(prec["verdict"]) if prec else None,
                                       key=f"vig_v_{uid}_{i}", horizontal=False)
                        com = c2.text_area("Commentaire (obligatoire)", key=f"vig_t_{uid}_{i}", height=80,
                                           value=(f"Idem analyse du {str(prec['ts'])[:10]} : {prec['commentaire']}"
                                                  if prec else ""),
                                           placeholder="ex. homonyme : date de naissance et nationalité différentes")
                        verdicts.append({"rubrique": rub, "rang": rang, "valeur": val, "resultat": raw,
                                         "statut": stt, "verdict": ver, "commentaire": com})
                    if not points:
                        st.info("Aucun point détaillé : contrôles de structure à examiner.")
                        com = st.text_area("Commentaire (obligatoire)", key=f"vig_t_{uid}_x")
                        ver = st.radio("Analyse", list(vg.VERDICTS), format_func=vg.VERDICTS.get, index=None,
                                       key=f"vig_v_{uid}_x")
                        verdicts = [{"rubrique": "Contrôles de structure", "rang": 1, "valeur": "", "resultat": "",
                                     "statut": "A_VERIFIER", "verdict": ver, "commentaire": com}]
                    ok = st.form_submit_button("Enregistrer l'analyse", type="primary")
                if ok:
                    try:
                        evd = vg.analyse_points(jp, current_user(), uid, fs, verdicts, chemin,
                                                P.vigilance_dir / "analyses")
                        if evd["decision"] == "CONFIRMEE":
                            ed = pd.DataFrame([{"FICHIER": f, "AUDIT_SOURCE": None, "DECISION": "REJETE",
                                                "COMMENTAIRE": f"Vigilance : alerte avérée — {evd['motif']}"[:900]}
                                               for f in fs])
                            transfers.save_decisions(P.decisions_csv, ed, current_user())
                        audit(P.audit_log, f"VIGILANCE_{evd['decision']}", current_user(), uid=uid, tl=fs,
                              motif=evd["motif"])
                        st.session_state["vig_msg"] = ("TL libéré(s) : alerte non avérée." if evd["decision"] == "LEVEE"
                                                       else "Alerte avérée : TL rejeté(s).")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        if st.session_state.get("vig_msg"):
            st.success(st.session_state.pop("vig_msg"))

    # ---------- suivi
    with t_suivi:
        fp = vg.registre_faux_positifs(journal)
        if not fp.empty:
            with st.expander(f"Registre des alertes analysées ({len(fp)}) — reconnues automatiquement si elles ressortent"):
                st.dataframe(fp, hide_index=True, **_W())
                st.download_button("⬇ Registre des alertes analysées", to_excel_bytes({"ALERTES": fp}),
                                   file_name="registre_alertes_vigilance.xlsx", key="vig_fp_dl")
        df = _statut_frame(sy_val, st_map)
        if df.empty:
            st.info("Aucun TL validé dans ce lot d'extraction.")
        else:
            st.dataframe(df.drop(columns=["_annotee"]), hide_index=True, **_W(), height=380,
                         column_config={"Montant": st.column_config.NumberColumn(format="%.2f")})
            st.download_button("⬇ Suivi vigilance (Excel)", to_excel_bytes({"VIGILANCE": df.drop(columns=["_annotee"])}),
                               file_name="suivi_vigilance.xlsx")
            ann = sorted({a for a in df["_annotee"].dropna() if Path(a).exists()})
            if ann:
                pick = st.selectbox("Fiches annotées (analyse des HIT)", ann, format_func=lambda a: Path(a).name,
                                    key="vig_ann")
                st.download_button("⬇ Fiche annotée", Path(pick).read_bytes(), file_name=Path(pick).name,
                                   key="vig_ann_dl")


def statut_map(P) -> dict[str, str]:
    """{fichier: statut} pour le registre."""
    return {f: v["statut"] for f, v in vg.statuses(vg.read_journal(vg.journal_path(P))).items()
            if not is_blank(v.get("statut"))}
