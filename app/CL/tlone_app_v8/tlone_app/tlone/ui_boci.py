"""Écrans des fichiers BOCI (Trade, DOM, Règlement) et du fichier Trade pour l'agence."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from . import boci, execution, referentiels, transfers
from .common import audit, current_user, to_excel_bytes
from .ui import W, fmt_dzd, hauteur, historique_data


def contexte(P, s) -> dict:
    """Tout ce qu'il faut pour savoir quels TL sont prêts : historique (Trade / Atlas / blocages / soldes),
    lot OV contrôlé, décisions, vigilance, Planning."""
    from . import planning, ui_ov, ui_vigilance
    files, data, res, errs, _ = historique_data(P, s)
    audits = transfers.latest_audit(P.tr_out)
    A = SY = CH = None
    if audits:
        A, SY, CH, _pl = ui_ov.load(P, s, audits[0])
    PL = planning.load_planning(P.planning_csv)
    vig = ui_vigilance.statut_map(P)
    dec = transfers.load_decisions(P.decisions_csv)
    plan = execution.plan(data.get("trade"), data.get("atlas"), data.get("blocage"), data.get("soldes"), SY, CH,
                          dec, vig, majoration=s.provision_majoration_dzd, tol=s.tolerance_montant_dzd, planning=PL,
                          marge_min=s.blocage_marge_min_dzd, arrondi=s.blocage_arrondi_dzd) \
        if data.get("trade") is not None else pd.DataFrame()
    return {"files": files, "data": data, "res": res, "errs": errs, "A": A, "SY": SY, "CH": CH, "PL": PL,
            "vig": vig, "dec": dec, "plan": plan}


def _next_business_day(d: date) -> date:
    d = d + timedelta(days=1)
    while d.weekday() in (4, 5):     # vendredi / samedi
        d += timedelta(days=1)
    return d


def _save_envoi(P, files: dict[str, bytes], names: dict[str, str], lignes: pd.DataFrame, dv: date | None) -> Path:
    d = P.boci_out / names["trade"].split("_")[-1].replace(".xlsx", "")
    d.mkdir(parents=True, exist_ok=True)
    for k, b in files.items():
        (d / names[k]).write_bytes(b)
    lignes.to_csv(d / "lignes_preparees.csv", index=False, encoding="utf-8-sig")
    (d / "envoi.json").write_text(json.dumps({
        "date_valeur": dv.isoformat() if dv else "(à renseigner par le BOCI)", "nb_tl": len(lignes), "montant_total": float(lignes["MONTANT"].sum()),
        "par_devise": lignes.groupby("DEVISE")["MONTANT"].sum().round(2).to_dict(), "tl": list(lignes["REF_TL"]),
        "genere_par": current_user(), "genere_le": datetime.now().isoformat(timespec="seconds"), "fichiers": names},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def render_final(P, s, ctx: dict) -> None:
    plan = ctx["plan"]
    if plan is None or plan.empty:
        st.info("Aucun TL en attente : déposez l'export CarthagoTrade (page Historique TL, onglet ① Fichiers).")
        return
    prets = plan[plan["STATUT"] == "A_EXECUTER"]
    c = st.columns(4)
    c[0].metric("TL prêts à exécuter", len(prets))
    c[1].metric("Montant (DZD)", fmt_dzd(prets["MONTANT_TL"].sum()))
    c[2].metric("En attente (blocage, complément…)", int((plan["STATUT"] != "A_EXECUTER").sum()))
    c[3].metric("Doublons écartés", int((plan["STATUT"] == "DOUBLON").sum()))
    st.caption("Un TL est prêt quand : dossier OV scanné, contrôlé et validé · vigilance RAS ou HIT levé · fonds bloqués "
               "(≥ OV + 3 700 DZD) · pas de doublon de période · présent dans CarthagoTrade (saisi et validé par l'agence).")
    att = plan[plan["STATUT"] != "A_EXECUTER"]
    if not att.empty:
        with st.expander(f"Pourquoi {len(att)} TL en attente ?", expanded=prets.empty):
            cols = [c for c in ("REF_TL", "NOM", "PERIODE", "MONTANT_OV", "MONTANT_TL", "STATUT", "BLOCAGE", "MONTANT_BLOQUE",
                                "RESTE_A_BLOQUER", "MOTIFS") if c in att.columns]
            v = att[cols].assign(STATUT=att["STATUT"].map(execution.LIB_STATUT))
            if "BLOCAGE" in v:
                v["BLOCAGE"] = v["BLOCAGE"].map(execution.LIB_BLOCAGE)
            st.dataframe(v, hide_index=True, **W,
                         height=hauteur(len(att)), column_config={k: st.column_config.NumberColumn(format="%.2f")
                                                                  for k in ("MONTANT_OV", "MONTANT_TL", "MONTANT_BLOQUE", "RESTE_A_BLOQUER")})
            st.caption("Blocage « À bloquer » : fichier de blocages pour l'agence sur la page Exécution & suivi, onglet ② "
                       "(sans attendre la conformité). « Complément » : corriger ou valider le dossier OV.")
    if prets.empty:
        st.warning("Aucun TL prêt pour le moment : voir le motif de chaque TL en attente ci-dessus.")
        return
    params = boci.load_params(P)
    R = referentiels.load_all(P)
    lignes = boci.preparer(prets, ctx["data"].get("trade"), ctx["SY"], ctx["A"], R["rh"], ctx["PL"],
                           boci.carthago_dom_dates(P.carthago_xlsx), params)
    ok = lignes[lignes["BLOQUANTS"] == ""]
    ko = lignes[lignes["BLOQUANTS"] != ""]
    st.markdown("**Préparation des lignes** — une ligne par TL ; chaque valeur indique sa source (OV, base RH, Trade, Planning).")
    st.dataframe(lignes[["REF_TL", "NOM_CLIENT", "PERIODE", "MONTANT", "DEVISE", "BENEFICIAIRE", "IBAN", "SWIFT", "BANQUE",
                         "DOMICILIATION", "BLOQUANTS", "A_VERIFIER", "SOURCES"]], hide_index=True, **W, height=hauteur(len(lignes)),
                 column_config={"MONTANT": st.column_config.NumberColumn(format="%.2f")})
    if not ko.empty:
        st.error(f"{len(ko)} TL écarté(s) : informations obligatoires manquantes (colonne BLOQUANTS).")
    st.caption("Date valeur, DATE VAL et DATE VAL1 laissées vides : le BOCI les renseigne après la salle des marchés. "
               "Objet du transfert et REF_DENO au format MMAAAA[P1|P2] ; référence de dénotage Trade AAAA-MM[P1|P2] ; "
               "« Name CLIENT » du Règlement = nom de la base RH.")
    dv = None
    if ok.empty:
        return
    out = boci.generer(ok, dv, params)
    an = boci.verifier(out, params, ctx["PL"])
    nb = int((an["NIVEAU"] == "BLOQUANT").sum()) if not an.empty else 0
    (st.success if not len(an) else st.warning if not nb else st.error)(
        f"Contrôle automatique des 3 fichiers : {len(an)} point(s), dont {nb} bloquant(s)." if len(an)
        else f"Contrôle automatique des 3 fichiers : aucun écart ({len(ok)} TL, valeurs fixes respectées, fichiers cohérents).")
    if len(an):
        st.dataframe(an, hide_index=True, **W, height=hauteur(len(an), 260))
    tot = ok.groupby("DEVISE")["MONTANT"].agg(["count", "sum"]).reset_index()
    st.caption("Par devise : " + " · ".join(f"{r.DEVISE} : {int(r['count'])} TL, {fmt_dzd(r['sum'])} DZD" for _, r in tot.iterrows()))
    names = boci.file_names(len(ok))
    xl = {k: boci.to_xlsx(k, out[k]) for k in out}
    confirm = st.checkbox(f"Je confirme la génération des fichiers BOCI pour {len(ok)} TL",
                          disabled=nb > 0, key="boci_ok")
    if st.button("📦 Générer et archiver les 3 fichiers", type="primary", disabled=nb > 0 or not confirm):
        d = _save_envoi(P, xl, names, ok, dv)
        audit(P.audit_log, "BOCI_FICHIERS", current_user(), dossier=str(d), nb_tl=len(ok))
        st.session_state["boci_last"] = str(d)
        st.success(f"Fichiers archivés dans `{d}`.")
    cols = st.columns(3)
    for col, k in zip(cols, ("trade", "dom", "reglement")):
        col.download_button(f"⬇ {boci.LABEL[k]} ({len(out[k])})", xl[k], file_name=names[k], key=f"dl_boci_{k}",
                            disabled=nb > 0)
    with st.expander("Aperçu des fichiers"):
        for k in ("trade", "dom", "reglement"):
            st.markdown(f"**{names[k]}**")
            st.dataframe(out[k], hide_index=True, **W, height=hauteur(len(out[k]), 260))


def render_agence(P, s, ctx: dict) -> None:
    st.caption("Après lecture et validation des OV : pré-saisie pour l'agence (création des TL dans CarthagoTrade). "
               "Mêmes colonnes que le fichier Trade ; la référence TL, le statut, l'étape et la date valeur sont "
               "attribués ensuite par CarthagoTrade / le BOCI.")
    SY, dec = ctx["SY"], ctx["dec"]
    if SY is None or SY.empty:
        st.info("Aucun lot OV extrait.")
        return
    val = set(dec[dec["DECISION"] == "VALIDE"]["FICHIER"]) if not dec.empty else set()
    sel = SY[SY["FICHIER"].isin(val)]
    st.metric("OV validés", len(sel))
    if sel.empty:
        st.info("Aucun OV validé (page Transferts OV, onglet ③).")
        return
    # TL déjà saisis dans CarthagoTrade (même client, même période, non rejetés) : rien à pré-saisir
    tr = ctx["data"].get("trade")
    if tr is not None and not tr.empty:
        from . import historique as h
        t = tr[tr["STATUT_TRADE"].map(h._statut_key) != "REJETE"]
        deja = set(zip(t["CLIENT"].astype(str), t["PERIODE"].astype(str)))
        dans = [(str(c), str(p)) in deja for c, p in zip(sel["SIEGE_RACINE"], sel["PERIODE_TL"])]
        n_deja = sum(dans)
        sel = sel[[not x for x in dans]]
        if n_deja:
            st.caption(f"{n_deja} OV validé(s) déjà saisi(s) dans CarthagoTrade (même salarié, même période) : exclus.")
        if sel.empty:
            st.success("Tous les OV validés sont déjà saisis dans CarthagoTrade : rien à pré-saisir.")
            return
    else:
        st.caption("Export CarthagoTrade absent (page Exécution & suivi, onglet ①) : les OV déjà saisis ne peuvent "
                   "pas être exclus.")
    prets = pd.DataFrame({"REF_TL": "", "CLIENT": sel["SIEGE_RACINE"], "NOM": sel["NOM"], "PERIODE": sel["PERIODE_TL"],
                          "MONTANT_TL": sel["MONTANT_OV"], "DOSSIER_TLONE": sel["FICHIER"]})
    prets["REF_TL"] = [f"OV:{f}" for f in sel["FICHIER"]]
    R = referentiels.load_all(P)
    params = boci.load_params(P)
    lignes = boci.preparer(prets, ctx["data"].get("trade"), SY, ctx["A"], R["rh"], ctx["PL"],
                           boci.carthago_dom_dates(P.carthago_xlsx), params)
    df = boci.trade_agence(lignes, params)
    df.insert(0, "Dossier TL-One", [x[3:] for x in lignes["REF_TL"]])
    st.dataframe(df, hide_index=True, **W, height=hauteur(len(df)))
    st.download_button("⬇ Fichier Trade pour l'agence", to_excel_bytes({"Trade_agence": df}),
                       file_name=f"Trade_agence_{datetime.now():%Y%m%dT%H%M%S}.xlsx", type="primary")


def render_check(P, s, ctx: dict) -> None:
    st.caption("Déposez des fichiers Trade / DOM / Règlement (générés ou préparés à la main) : TL-One vérifie les valeurs "
               "fixes, les formats (IBAN, SWIFT, RIB, périodes) et la cohérence de chaque TL entre les 3 fichiers.")
    ups = st.file_uploader("Fichiers BOCI", type=["xlsx"], accept_multiple_files=True, key="boci_chk")
    if not ups:
        return
    F, unknown = {}, []
    for u in ups:
        k, df = boci.read_file(u.getvalue())
        if k:
            F[k] = df
        else:
            unknown.append(u.name)
    if unknown:
        st.warning("Type non reconnu : " + ", ".join(unknown))
    st.caption("Reconnus : " + ", ".join(f"{boci.LABEL[k]} ({len(v)} lignes)" for k, v in F.items()))
    an = boci.verifier(F, boci.load_params(P), ctx["PL"])
    c = st.columns(3)
    c[0].metric("🔴 Bloquants", int((an["NIVEAU"] == "BLOQUANT").sum()))
    c[1].metric("🟡 À vérifier", int((an["NIVEAU"] == "A_VERIFIER").sum()))
    c[2].metric("TL contrôlés", max(len(df) for df in F.values()) if F else 0)
    if an.empty:
        st.success("Aucune anomalie.")
        return
    codes = sorted(an["CODE"].unique())
    pick = st.multiselect("Filtrer", codes, key="boci_chk_f",
                          format_func=lambda x: f"{x} — {an.loc[an['CODE'] == x, 'ANOMALIE'].iloc[0]}")
    v = an[an["CODE"].isin(pick)] if pick else an
    st.dataframe(v, hide_index=True, **W, height=hauteur(len(v), 460))
    st.download_button("⬇ Rapport de contrôle", to_excel_bytes({"ANOMALIES": an}), file_name="controle_fichiers_BOCI.xlsx")


def render_params(P, s) -> None:
    params = boci.load_params(P)
    st.caption("Référentiel utilisé pour les fichiers BOCI : nom de banque et pays par BIC, compte correspondant par "
               "devise, banque intermédiaire, options. Modifier le fichier puis le redéposer.")
    a, b = st.columns(2)
    a.download_button("⬇ Paramètres BOCI (Excel)", to_excel_bytes(params), file_name="boci_parametres.xlsx")
    up = b.file_uploader("Redéposer les paramètres", type=["xlsx"], key="boci_par_up")
    if up and b.button("Enregistrer les paramètres"):
        P.referentiels_dir.mkdir(parents=True, exist_ok=True)
        boci.params_path(P).write_bytes(up.getvalue())
        audit(P.audit_log, "BOCI_PARAMETRES", current_user(), fichier=up.name)
        st.rerun()
    for k, df in params.items():
        st.markdown(f"**{k}**")
        st.dataframe(df, hide_index=True, **W)
    st.markdown("**Valeurs fixes (feuilles « valeur fix » des modèles)**")
    st.dataframe(pd.DataFrame([{"Fichier": boci.LABEL[k], "Colonne": c, "Valeur": v or "(toujours vide)", "Type": t}
                               for t, src in (("fixe", boci.FIXES), ("constante observée", boci.CONSTANTES))
                               for k, d in src.items() for c, v in d.items()]), hide_index=True, **W)


def render_envois(P) -> None:
    d = P.boci_out
    envs = sorted((x for x in d.iterdir() if x.is_dir()), reverse=True) if d.exists() else []
    if not envs:
        st.info("Aucun envoi archivé.")
        return
    rows = []
    for e in envs:
        try:
            j = json.loads((e / "envoi.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            j = {}
        rows.append({"Envoi": e.name, "Date valeur": j.get("date_valeur"), "TL": j.get("nb_tl"),
                     "Montant DZD": j.get("montant_total"), "Par": j.get("genere_par"), "Le": j.get("genere_le")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, **W)
    pick = st.selectbox("Télécharger les fichiers d'un envoi", [e.name for e in envs], key="boci_env")
    for f in sorted((d / pick).glob("*.xlsx")):
        st.download_button(f"⬇ {f.name}", f.read_bytes(), file_name=f.name, key=f"env_{f.name}")
