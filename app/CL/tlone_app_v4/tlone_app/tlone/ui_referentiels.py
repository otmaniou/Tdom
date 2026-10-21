"""Écran « Référentiels du mois » : base RH, ATF, autorisations (dépôt, contrôle, aperçu)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import referentiels, rh, transfers
from .common import audit, current_user, to_excel_bytes
from .ui import W

RH_TEMPLATE = ["Matricule SAP", "Matricule Kelio", "NOM ET PRENOM", "Nom", "Prénom", "DATE DE NAISSANCE",
               "Lieu de naissance", "NOM DU PERE", "NOM DE LA MERE", "Date d'entrée en Algérie", "Fonction",
               "Qualification", "Permit travail n°", "DATE DE DELIVRANCE", "Date d'émission", "Fin de validité",
               "DUREE DU PERMIS DE TRAVAIL (Mois)", "Date d'attestation", "Salaire Poste", "Retenue SS", "IRG",
               "Retenue Mutuelle", "Salaire Net", "Part transférable", "Part Payable", "Compte bancaire (Algérie)",
               "Nom de banque (Algérie)", "Agence de bank (Algérie)", "Compte devise", "Nom de banque (Etrange)",
               "Pays de la banque (Etrange)", "Nom du bénéficiaire", "Prénom du bénéficiaire", "Devise du transfert",
               "MOIS DE PAIEMENT", "SWIFT/BIC", "Adresse", "Contrat N°", "Date d'établissement", "Nombre de jours", "PART"]
ATF_TEMPLATE = ["SIRA", "MATRICULE SAP", "Nom et Prenom", "Adresse", "NET IMPOSABLE", "IRG", "SALAIRE NET",
                "MONTANT TRANSFERABLE", "BANQUE", "periode"]


def render(P, s, planning: pd.DataFrame | None = None) -> None:
    R = referentiels.load_all(P)
    rhdf, atf, aut = R["rh"], R["atf"], R["aut"]
    mois = sorted({m for m in rhdf["MOIS"].dropna()}) if not rhdf.empty else []
    c = st.columns(4)
    c[0].metric("Salariés (base RH, dernier mois)", rhdf[rhdf["MOIS"] == mois[-1]]["CLIENT"].nunique() if mois else 0)
    c[1].metric("Mois couverts par la base RH", len(mois))
    c[2].metric("Lignes ATF", len(atf))
    c[3].metric("Autorisations", len(aut))
    for e in R["errors"]:
        st.warning(e)
    tabs = st.tabs(["Base RH", "ATF", "Autorisations", "Planning × base RH"])
    for t, kind in zip(tabs[:3], ("rh", "atf", "aut")):
        with t:
            meta = referentiels.KINDS[kind]
            st.caption(meta["aide"])
            a, b = st.columns([3, 1])
            ups = a.file_uploader(f"Déposer {meta['label']}", type=meta["types"], accept_multiple_files=True,
                                  key=f"ref_up_{kind}")
            tpl = {"rh": RH_TEMPLATE, "atf": ATF_TEMPLATE, "aut": transfers.AUT_COLUMNS}[kind]
            b.download_button("Modèle (en-têtes)", to_excel_bytes({meta["label"]: pd.DataFrame(columns=tpl)}),
                              file_name=f"modele_{meta['dir']}.xlsx", key=f"ref_tpl_{kind}")
            annee = None
            if kind == "aut" and ups and any(u.name.lower().endswith((".html", ".htm")) for u in ups):
                from datetime import date as _date
                from . import autorisations
                d0 = _date.today()
                annee = a.number_input("Année des autorisations du portail (la désignation « NOM (AOUT) » ne la donne pas)",
                                       min_value=2015, max_value=2100, value=autorisations.annee_depuis_nom(ups[0].name) or d0.year,
                                       key="ref_aut_annee")
                dval = a.date_input("Date de validation de la demande (validité 45 jours, absente de la page)",
                                    value=d0, format="DD/MM/YYYY", key="ref_aut_dval")
            if ups and a.button(f"Enregistrer {len(ups)} fichier(s)", key=f"ref_save_{kind}", type="primary"):
                errs = []
                for u in ups:
                    nom = u.name
                    if annee and nom.lower().endswith((".html", ".htm")):
                        from . import autorisations
                        if not autorisations.annee_depuis_nom(nom):
                            nom = f"{int(annee)}_{nom}"
                    p = referentiels.save(P, kind, nom, u.getbuffer().tobytes())
                    if annee and nom.lower().endswith((".html", ".htm")):
                        import json as _json
                        p.with_name(p.name + ".json").write_text(_json.dumps(
                            {"annee": int(annee), "date_validation": dval.strftime("%d/%m/%Y")}), encoding="utf-8")
                    try:
                        if kind == "rh":
                            rh.read(p)
                        else:
                            transfers.load_referential(p, transfers.ATF_COLUMNS if kind == "atf" else transfers.AUT_COLUMNS)
                    except Exception as exc:  # noqa: BLE001
                        errs.append(f"{u.name} : {exc}")
                        p.unlink(missing_ok=True)
                    audit(P.audit_log, f"REFERENTIEL_{kind.upper()}", current_user(), fichier=u.name)
                for e in errs:
                    st.error(e)
                st.cache_data.clear()
                st.cache_resource.clear()
                st.rerun()
            fs = referentiels.files(P, kind)
            if fs:
                st.caption("Fichiers : " + " · ".join(f"`{p.name}`" for p in fs[-6:]))
            if kind == "aut":
                _portail(P, s, [p for p in fs if p.suffix.lower() in (".html", ".htm")])
            df = {"rh": rhdf, "atf": atf, "aut": aut}[kind]
            if df.empty:
                st.info(f"Aucun fichier {meta['label']} exploitable.")
                continue
            if kind == "rh":
                q = rh.dq(rhdf)
                nb = int((q["NIVEAU"] == "BLOQUANT").sum())
                (st.error if nb else st.warning if len(q) else st.success)(
                    f"Contrôle qualité de la base RH : {len(q)} point(s), dont {nb} bloquant(s)"
                    if len(q) else "Contrôle qualité de la base RH : aucun écart (RIB, IBAN, SWIFT, part 95 % × net × jours/30).")
                if len(q):
                    st.dataframe(q, hide_index=True, **W)
                show = ["MATRICULE", "NOM_PRENOM", "CLIENT", "PERIODE", "NB_JOURS", "SALAIRE_NET", "PART_TRANSFERABLE",
                        "DEVISE", "BENEFICIAIRE", "IBAN", "SWIFT", "BANQUE_ETR", "PAYS_BANQUE", "PERMIS", "PERMIS_FIN", "SOURCE"]
                st.dataframe(rhdf[show], hide_index=True, **W, height=360)
            else:
                st.dataframe(df.drop(columns=[c for c in ("_COMPTE",) if c in df]), hide_index=True, **W, height=320)
    with tabs[3]:
        st.caption("Chaque salarié de la base RH face au Planning TL : sa domiciliation couvre-t-elle la période "
                   "(P1 ancien contrat, P2 nouveau contrat) et la part transférable est-elle la même ?")
        pv = rh.planning_vs_rh(planning if planning is not None else pd.DataFrame(), rhdf)
        if pv.empty:
            st.info("Base RH ou Planning absent.")
        else:
            cnt = pv["STATUT"].value_counts()
            k = st.columns(4)
            for i, (code, lab) in enumerate((("OK", "✅ Conformes"), ("ECART", "🟠 Écarts"),
                                             ("PERIODE_NON_DOMICILIEE", "🗓️ Période non domiciliée"),
                                             ("DOM_ABSENTE", "🔴 DOM absente"))):
                k[i].metric(lab, int(cnt.get(code, 0)))
            st.dataframe(pv, hide_index=True, **W, height=360)
            st.download_button("⬇ Rapprochement Planning × RH", to_excel_bytes({"PLANNING_RH": pv}),
                               file_name="planning_x_base_rh.xlsx")


def _portail(P, s, fichiers) -> None:
    """Demandes du portail : en-tête (NIF, raison sociale, total, articles) et contrôles, NIF de l'employeur compris."""
    if not fichiers:
        return
    from . import autorisations, employeurs
    e = employeurs.get(s.home or P.data_root, s.employeur) if s.employeur else None
    nif = (e or {}).get("NIF")
    rows = []
    for p in fichiers[-12:]:
        raw = p.read_bytes()
        if not autorisations.est_portail(raw):
            rows.append({"Fichier": p.name, "Contrôles": "Page sans le tableau du portail"})
            continue
        res = autorisations.lire(raw, nom_fichier=p.name)
        _, ctl = autorisations.vers_referentiel(res, nif)
        en = res["entete"]
        rows.append({"Fichier": p.name, "Mois": ", ".join(sorted(res["lignes"]["MOIS"].dropna().unique())),
                     "NIF": en.get("NIF"), "Raison sociale": en.get("RAISON_SOCIALE"), "Articles": en.get("NB_ARTICLES"),
                     "Lus": len(res["lignes"]), "Total de la demande": en.get("TOTAL_DEMANDE"),
                     "Somme lue": round(float(res["lignes"]["MONTANT_AUTORISE"].sum()), 2),
                     "Contrôles": " | ".join(ctl) or "✅ NIF, nombre d'articles et total concordants"})
    st.markdown("**Demandes du portail « Transfert des salaires des expatriés »**")
    if not nif:
        st.caption("NIF de l'employeur non renseigné (page Employeurs) : le NIF de la demande n'est pas contrôlé.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, **W)
