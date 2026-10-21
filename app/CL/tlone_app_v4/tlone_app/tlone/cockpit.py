"""Accueil « cockpit » : indicateurs du parcours d'un TL, de la DOM scannée à l'exécution Atlas."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from . import boci, employeurs, execution, historique, referentiels, rh, transfers


def _nb_controles() -> int:
    """Nombre de contrôles automatiques distincts : OV (T), base RH (R, RH), historique (H), fichiers BOCI
    (B, C, F, P) et contrôles de la matrice DOM (une règle par ligne de la matrice)."""
    here = Path(__file__).parent
    codes = set()
    for f, pat in (("transfers.py", r'"(T\d{2}b?|R0\d)"'), ("historique.py", r'"(H\d{2}b?)"'), ("rh.py", r'"(RH\d{2})"'),
                   ("boci.py", r'"([BCFP]\d{2})"')):
        try:
            codes |= set(re.findall(pat, (here / f).read_text(encoding="utf-8")))
        except OSError:
            pass
    try:
        from .matrice import LIGNES
        codes |= {f"DOM:{lg.key}" for lg in LIGNES}
    except Exception:  # noqa: BLE001
        pass
    return len(codes)


NB_CONTROLES = _nb_controles()


def indicateurs(P, s) -> dict:
    from . import domvalid, planning
    from .ui_boci import contexte
    K: dict = {"nb_controles": NB_CONTROLES}
    try:
        ctx = contexte(P, s)
    except Exception:  # noqa: BLE001  un fichier illisible ne doit pas empêcher l'accueil
        ctx = {"plan": pd.DataFrame(), "SY": None, "data": {}, "res": {"anomalies": pd.DataFrame()}, "PL": pd.DataFrame(),
               "vig": {}, "dec": pd.DataFrame()}
    PL = ctx["PL"] if ctx.get("PL") is not None else planning.load_planning(P.planning_csv)
    R = referentiels.load_all(P)
    rhdf = R["rh"]
    last = sorted(rhdf["MOIS"].dropna().unique())[-1] if not rhdf.empty and rhdf["MOIS"].notna().any() else None
    K["rh_mois"] = last
    K["salaries"] = int(rhdf[rhdf["MOIS"] == last]["CLIENT"].nunique()) if last else (
        int(PL["SIEGE_RACINE"].nunique()) if not PL.empty else 0)
    K["rh_dq"] = len(rh.dq(rhdf)) if not rhdf.empty else 0
    pv = rh.planning_vs_rh(PL, rhdf) if not rhdf.empty else pd.DataFrame(columns=["STATUT"])
    K["rh_planning_ecarts"] = int((pv["STATUT"] != "OK").sum())
    K["doms"] = int(PL["DOM_ID"].nunique()) if not PL.empty else 0
    K["periodes"] = len(PL)
    K["dom_dossiers"] = K["dom_restant"] = K["dom_valides"] = 0
    if P.validation_xlsx.exists():
        try:
            from . import matrice as mx
            lot = mx.load_lot(P)
            sm = [mx.summary(m) for m in mx.build_all(lot, mx.read_journal(P.dom_journal), mx.default_sources(
                P.sources_reference_xlsx if P.sources_reference_xlsx.exists() else None))]
            K["dom_dossiers"] = len(sm)
            K["dom_restant"] = sum(1 for x in sm if x["STATUT"] == "À traiter")
            K["dom_valides"] = sum(1 for x in sm if x["STATUT"] == "Validé")
        except Exception:  # noqa: BLE001
            try:
                K["dom_dossiers"] = len(domvalid.load_sheet(P.validation_xlsx, domvalid.DOSSIERS_SHEET))
            except Exception:  # noqa: BLE001
                pass
    SY = ctx.get("SY")
    dec = ctx.get("dec") if ctx.get("dec") is not None else pd.DataFrame()
    K["ov"] = len(SY) if SY is not None else 0
    for k, st in (("ov_conformes", "CONFORME"), ("ov_revoir", "A_REVOIR"), ("ov_nc", "NON_CONFORME")):
        K[k] = int((SY["STATUT_CONTROLE"] == st).sum()) if SY is not None and not SY.empty else 0
    val = set(dec[dec["DECISION"] == "VALIDE"]["FICHIER"]) if not dec.empty else set()
    K["ov_valides"] = len(val & set(SY["FICHIER"])) if SY is not None and not SY.empty else 0
    vig = ctx.get("vig") or {}
    K["vig_ras"] = sum(1 for v in vig.values() if v in ("RAS", "HIT_LEVE"))
    K["vig_hit"] = sum(1 for v in vig.values() if v in ("HIT", "A_VERIFIER"))
    K["vig_attente"] = sum(1 for v in vig.values() if v == "EN_ATTENTE")
    K["vig_a_faire"] = len(val) - len([f for f in val if f in vig])
    plan = ctx.get("plan") if ctx.get("plan") is not None else pd.DataFrame()
    cnt = plan["STATUT"].value_counts() if not plan.empty else pd.Series(dtype=int)
    for k in ("A_EXECUTER", "A_BLOQUER", "SOLDE_INSUFFISANT", "COMPLEMENT", "DOUBLON", "ANOMALIE"):
        K[k.lower()] = int(cnt.get(k, 0))
    K["prets"] = K["a_executer"]
    K["trade_saisis"] = len(plan) - K["anomalie"] if not plan.empty else 0
    K["montant_prets"] = float(plan[plan["STATUT"] == "A_EXECUTER"]["MONTANT_TL"].sum()) if not plan.empty else 0.0
    dev = {}
    if not plan.empty and not rhdf.empty:
        dmap = rhdf.drop_duplicates("CLIENT", keep="last").set_index("CLIENT")["DEVISE"].to_dict()
        p = plan[plan["STATUT"] == "A_EXECUTER"]
        for cl, mt in zip(p["CLIENT"], p["MONTANT_TL"]):
            dev[dmap.get(cl, "?")] = dev.get(dmap.get(cl, "?"), 0) + float(mt or 0)
    K["par_devise"] = dev
    data = ctx.get("data") or {}
    at = data.get("atlas")
    K["executes"] = int(at["REF_TL"].nunique()) if at is not None and not at.empty else 0
    an = (ctx.get("res") or {}).get("anomalies")
    an = an if an is not None else pd.DataFrame(columns=["GRAVITE"])
    K["hist_critiques"] = int((an["GRAVITE"] == "CRITIQUE").sum()) if not an.empty else 0
    K["hist_anomalies"] = int(an["GRAVITE"].isin(["CRITIQUE", "ELEVEE"]).sum()) if not an.empty else 0
    K["reliquats"] = 0
    K["reliquat_montant"] = 0.0
    if not PL.empty:
        try:
            sp = execution.suivi_planning(PL, transfers.load_registre(P.registre_csv), data.get("trade"), at,
                                          tol=s.tolerance_montant_dzd)
            K["reliquats"] = int((sp["STATUT_PERIODE"] == "NON_TRANSFERE").sum())
            K["reliquat_montant"] = float(sp.loc[sp["STATUT_PERIODE"] == "NON_TRANSFERE", "RELIQUAT"].sum())
        except Exception:  # noqa: BLE001
            pass
    K["envois_boci"] = len([d for d in P.boci_out.iterdir() if d.is_dir()]) if P.boci_out.exists() else 0
    K["anomalies"] = (K["dom_restant"] + K["ov_nc"] + K["ov_revoir"] + K["rh_dq"] + K["rh_planning_ecarts"] + K["hist_anomalies"]
                      + K["anomalie"] + K["doublon"])
    return K


def _fmt(v) -> str:
    try:
        return f"{float(v):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def etapes(K: dict) -> list[dict]:
    dev = " · ".join(f"{d} {_fmt(m)}" for d, m in K.get("par_devise", {}).items()) or "—"
    return [
        dict(n=1, t="DOM scannées → lecture IA", a="Data · IA (lecture des scans)", k=f"{K['dom_dossiers']} dossiers",
             s=f"{K['dom_restant']} dossier(s) avec écart à arbitrer · {K['dom_valides']} validé(s)", page="pages/1_Controles_DOM.py"),
        dict(n=2, t="Planning TL du contrat", a="Data", k=f"{K['doms']} DOM · {K['periodes']} périodes",
             s=f"{K['reliquats']} période(s) échue(s) non transférée(s) — reliquat {_fmt(K['reliquat_montant'])} DZD",
             page="pages/2_Planning_TL.py"),
        dict(n=3, t="Base RH · ATF · autorisations", a="Employeur → Data", k=f"{K['salaries']} salariés",
             s=f"mois {K.get('rh_mois') or '—'} · {K['rh_dq']} anomalie(s) RH · {K['rh_planning_ecarts']} écart(s) Planning×RH",
             page="pages/3_Transferts_OV.py", lien="Référentiels du mois"),
        dict(n=4, t="OV scannés → lecture IA + contrôles", a="Data · IA (lecture des scans)", k=f"{K['ov']} OV lus",
             s=f"{K['ov_conformes']} conformes · {K['ov_revoir']} à revoir · {K['ov_nc']} non conformes · {K['ov_valides']} validés",
             page="pages/3_Transferts_OV.py", lien="Dossiers & validation"),
        dict(n=5, t="Fichier Trade pour l'agence", a="Data → Agence", k=f"{K['ov_valides']} OV validés",
             s="pré-saisie des TL dans CarthagoTrade", page="pages/5_Fichiers_BOCI.py"),
        dict(n=6, t="Virement des salaires → blocages", a="Employeur → Agence", k=f"{K['a_bloquer']} à bloquer",
             s=f"{K['solde_insuffisant']} solde(s) insuffisant(s) · règle : solde − Σ(TL + 5 000) ≥ 0",
             page="pages/4_Historique_TL.py", lien="TL à exécuter"),
        dict(n=7, t="Agence : dossier physique, blocage, Carthago", a="Agence (MOCI)", k=f"{K['trade_saisis']} TL saisis",
             s=f"{K['anomalie']} anomalie(s) Trade/Atlas · {K['doublon']} doublon(s)", ext=True),
        dict(n=8, t="Vigilance → DSI → HIT → BOCI", a="Data · DSI · BOCI", k=f"{K['vig_ras']} RAS",
             s=f"{K['vig_hit']} HIT à analyser · {K['vig_attente']} retour(s) attendu(s) · {K['vig_a_faire']} à envoyer",
             page="pages/3_Transferts_OV.py", lien="Vigilance"),
        dict(n=9, t="Netting devises & date valeur", a="BOCI · Salle des marchés · Employeur", k=dev,
             s="achat des devises de l'employeur, revente aux salariés ; date valeur choisie par le BOCI", ext=True),
        dict(n=10, t="Fichiers Trade · DOM · Règlement", a="Data → BOCI (injection)", k=f"{K['prets']} TL prêts",
             s=f"{_fmt(K['montant_prets'])} DZD · {K['envois_boci']} envoi(s) archivé(s) · e-mail aux salariés à l'injection",
             page="pages/5_Fichiers_BOCI.py"),
        dict(n=11, t="RPA Atlas à date valeur → rapprochement", a="DSI · RPA → Data", k=f"{K['executes']} TL exécutés",
             s=f"{K['hist_critiques']} anomalie(s) critique(s) (double débit, rejeté débité…)",
             page="pages/4_Historique_TL.py", lien="Historique"),
    ]


def rangees(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def carte(e: dict) -> str:
    return (f"<div class='tl-step{' ext' if e.get('ext') else ''}'><span class='n'>{e['n']}</span>"
            f"<span class='t'>{e['t']}</span><div class='a'>{e['a']}</div><div class='k'>{e['k']}</div>"
            f"<div class='s'>{e['s']}</div></div>")


AVANT = """<div class='tl-box tl-old'><b>Avant : processus manuel</b><ul>
<li>Chaque pièce (DOM, CTR, CTS, permis, OV, Annexes, bulletin) relue à l'œil et ressaisie dans plusieurs outils
(CarthagoPredom, CarthagoDom, CarthagoTrade, fichiers de vigilance, fichiers BOCI).</li>
<li>Plafonds (Annexe II, 95 % du net, part domiciliée, ATF, autorisation) et cumul DOM calculés à la main.</li>
<li>Ordre de grandeur déclaré : ~5 jours calendaires par dossier DOM, ~70 dossiers par mois, jusqu'à ~800
augmentations concentrées sur deux mois.</li>
<li>Fichiers Trade / DOM / Règlement préparés séparément : écarts possibles entre fichiers (période, IBAN, montant).</li>
<li>Doublons de période, reliquats et débits Atlas en double repérés tardivement.</li></ul></div>"""


def apres(K: dict) -> str:
    return f"""<div class='tl-box tl-new'><b>Avec TL-One</b><ul>
<li>L'IA lit les scans (DOM et OV) ; chaque valeur est affichée à côté de la page source, corrigeable et tracée.</li>
<li><b>{K['nb_controles']} contrôles automatiques</b> : plafonds, cumul DOM, base RH, ATF, autorisations, doublons,
RIB / IBAN / SWIFT, historique Atlas ; l'humain tranche les seuls points en écart.</li>
<li>La base RH de l'employeur (source des documents imprimés) contrôle l'OV, qui reste la base réglementaire du TL.</li>
<li>Fichiers BOCI produits à partir d'une seule ligne par TL : cohérents par construction et revérifiés
(valeurs fixes, formats, cohérence entre fichiers).</li>
<li>Plusieurs employeurs dans la même application ; chaque décision est journalisée (qui, quand, pourquoi).</li></ul></div>"""


def employeurs_resume(s) -> pd.DataFrame:
    from .config import load_settings
    home = s.home or s.paths.data_root
    reg = employeurs.load(home)
    rows = []
    for r in reg.itertuples():
        try:
            P = load_settings(r.CODE).paths
            from .planning import load_planning
            pl = load_planning(P.planning_csv)
            au = transfers.latest_audit(P.tr_out)
            rows.append({"Employeur": r.RAISON_SOCIALE, "NIF": r.NIF or "à compléter", "Code": r.CODE,
                         "DOM planifiées": int(pl["DOM_ID"].nunique()) if not pl.empty else 0,
                         "Lots OV": len(au), "Démo": "oui" if r.DEMO == "OUI" else ""})
        except Exception:  # noqa: BLE001
            continue
    return pd.DataFrame(rows)
