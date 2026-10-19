"""Matrice de validation des transferts (OV) : données × pièces, sur les contrôles T01–T17.

Colonnes : OV, Annexe I, Annexe II, Bulletin, Planning TL, ATF, Autorisation.
Les valeurs viennent du classeur OV (v26 / v27) ; les anomalies des contrôles de transfers.control_dossier.
Une correction saisie par le valideur remplace la valeur lue AVANT les contrôles : les contrôles
sont donc recalculés sur la valeur corrigée (journal append-only, jamais écrasé par l'extraction).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd

from .common import is_blank, name_similarity, parse_amount
from .matrice import append_event, display, read_journal, same  # noqa: F401  (réexport pour l'UI)
_REEXPORT = (append_event, read_journal)  # utilisés par l'UI via ov.append_event / ov.read_journal
from .transfers import parse_periode

COLS = ["OV", "ANNEXE_I", "ANNEXE_II", "BULLETIN", "PLANNING", "ATF", "AUTORISATION"]
COL_LABEL = {"OV": "OV", "ANNEXE_I": "Annexe I", "ANNEXE_II": "Annexe II", "BULLETIN": "Bulletin",
             "PLANNING": "Planning TL", "ATF": "ATF", "AUTORISATION": "Autorisation"}
EXTRACTED = {"OV", "ANNEXE_I", "ANNEXE_II", "BULLETIN"}   # colonnes corrigeables (lues par la VLM)
FEU = {"NON_CONFORME": "r", "A_REVOIR": "o", "CONFORME": "v"}


@dataclass(frozen=True)
class LigneOV:
    key: str
    label: str
    kind: str
    sources: dict          # col -> "GROUPE.clé" (audit v26) | "SY:COLONNE" (synthèse) | "PL:COLONNE" (planning)
    ref: str
    controls: tuple = ()
    compare: bool = True   # False : valeurs affichées pour information, sans comparaison entre pièces


LIGNES_OV = [
    LigneOV("nom", "Nom / bénéficiaire", "name",
            {"OV": "OV.beneficiaire_nom", "ANNEXE_I": "ANNEXE_I.nom_prenom", "ANNEXE_II": "ANNEXE_II.nom_prenom",
             "BULLETIN": "BULLETIN.nom_prenom", "PLANNING": "PL:NOM_TRAVAILLEUR"}, "PLANNING", ("T06",)),
    LigneOV("compte", "Compte local (débiteur)", "compte",
            {"OV": "OV.compte_debiteur", "ANNEXE_II": "ANNEXE_II.compte_bancaire", "PLANNING": "PL:DOM_COMPTE_LOCAL"},
            "PLANNING", ("T05",)),
    LigneOV("domref", "N° domiciliation (information)", "domref",
            {"ANNEXE_II": "ANNEXE_II.numero_domiciliation", "PLANNING": "PL:NUMERO_DOMICILIATION"}, "PLANNING",
            (), compare=False),
    LigneOV("periode", "Période", "periode",
            {"OV": "OV.periode", "ANNEXE_II": "ANNEXE_II.mois_transfert", "BULLETIN": "BULLETIN.mois_bulletin",
             "PLANNING": "PL:PERIODE_TL"}, "PLANNING", ("T07", "T04")),
    # Annexe II = salaire hors primes, bulletin = net avec primes : affichés sans comparaison
    LigneOV("salaire", "Salaire (Annexe II hors primes / net bulletin)", "amount",
            {"ANNEXE_II": "ANNEXE_II.salaire_mensuel", "BULLETIN": "BULLETIN.net_a_payer"}, "BULLETIN", (),
            compare=False),
    LigneOV("montant", "Montant OV (chiffres)", "amount", {"OV": "OV.montant_chiffres"}, "OV", ("T03", "T02")),
    LigneOV("lettres", "Montant en lettres", "text", {"OV": "OV.montant_lettres"}, "OV", ("T03", "T02")),
    LigneOV("plafond", "Plafond (montant max.)", "amount",
            {"ANNEXE_II": "ANNEXE_II.part_transferable", "BULLETIN": "SY:PLAFOND_95PCT_NET",
             "PLANNING": "SY:PLAFOND_DOM_PÉRIODE", "ATF": "SY:PLAFOND_ATF", "AUTORISATION": "SY:PLAFOND_AUTORISATION"},
            "", ("T09", "T10", "T11", "T12", "T13")),
    LigneOV("devise", "Devise", "text", {"OV": "OV.monnaie"}, "OV", ("T17",)),
    LigneOV("benef_compte", "Compte bénéficiaire", "text", {"OV": "OV.beneficiaire_compte"}, "OV", ("T02",)),
    LigneOV("swift", "SWIFT", "text", {"OV": "OV.swift"}, "OV", ("T02",)),
    LigneOV("banque", "Banque bénéficiaire", "text", {"OV": "OV.banque_nom"}, "OV", ("T02",)),
    LigneOV("date", "Date de la demande", "date", {"OV": "OV.date_demande"}, "OV", ()),
]
CAP_CONTROL = {"ANNEXE_II": "T09", "BULLETIN": "T10", "PLANNING": "T11", "ATF": "T12", "AUTORISATION": "T13"}
DOSSIER_CONTROLS = ("T01", "T01b", "T02", "T13b", "T14", "T14b", "T15")


def fold_ov(events: list[dict]) -> dict:
    st: dict = {}
    for ev in events:
        d = st.setdefault(str(ev.get("fichier")), {})
        k = str(ev.get("champ"))
        if ev.get("action") == "CORRIGE":
            d[k] = ev
        elif ev.get("action") == "ANNULE":
            d.pop(k, None)
    return st


def apply_corrections(audit: pd.DataFrame, journal: list[dict]) -> pd.DataFrame:
    """Valeurs corrigées par les valideurs, injectées avant les contrôles."""
    st = fold_ov(journal)
    if not st or audit.empty:
        return audit
    a = audit.copy()
    for f, champs in st.items():
        m = a["fichier"].astype(str) == f
        if not m.any():
            continue
        for champ, ev in champs.items():
            if champ not in a.columns:
                a[champ] = None
            a[champ] = a[champ].astype(object)
            a.loc[m, champ] = ev.get("valeur")
    return a


def _value(src: str, d: dict, sy: dict, pl: dict):
    if src.startswith("SY:"):
        if src == "SY:PLAFOND_95PCT_NET" and src[3:] not in sy:  # libellé dépendant de TLONE_PLAFOND_PCT_NET
            return next((v for k, v in sy.items() if k.startswith("PLAFOND_") and k.endswith("PCT_NET")), None)
        return sy.get(src[3:])
    if src.startswith("PL:"):
        return pl.get(src[3:])
    v = d.get(src)
    if src == "OV.periode" and not is_blank(d.get("OV.tranche")) and not is_blank(v):
        v = f"{v} — tranche {d.get('OV.tranche')}"
    return v


def _same_ov(kind, a, b):
    if kind == "periode":
        pa, pb = parse_periode(a)[0], parse_periode(b)[0]
        return (None, "") if not pa or not pb else (pa == pb, "")
    if kind == "text":
        return (None, "")
    return same(kind, a, b)


def build_ov(fichier: str, d: dict, sy: dict, checks: pd.DataFrame, planning: pd.DataFrame,
             corrections: dict, seuil_nom: float = 0.80) -> dict:
    pl = {}
    if sy.get("PERIODE_ID") and planning is not None and not planning.empty:
        r = planning[planning["PERIODE_ID"] == sy["PERIODE_ID"]]
        if not r.empty:
            pl = {k: (None if is_blank(v) else v) for k, v in r.iloc[0].to_dict().items()}
    ch = checks[checks["FICHIER"] == fichier] if checks is not None and not checks.empty else pd.DataFrame()
    ko = {r["CODE"]: r for _, r in ch.iterrows() if r["RESULTAT"] == "KO"}
    nc = {r["CODE"]: r for _, r in ch.iterrows() if r["RESULTAT"] == "NON_CONTROLABLE"}
    montant = parse_amount(d.get("OV.montant_chiffres"))
    rows = []
    for lg in LIGNES_OV:
        cells = {}
        for c in COLS:
            src = lg.sources.get(c)
            cell = {"col": c, "src": src, "present": src is not None, "value": None, "text": None,
                    "issues": [], "edit": None}
            if src is None:
                cells[c] = cell
                continue
            v = _value(src, d, sy, pl)
            ev = corrections.get(src) if src and "." in src and not src.startswith(("SY:", "PL:")) else None
            if ev:
                cell["edit"] = ev
            cell["value"] = None if is_blank(v) else v
            cell["text"] = (display("amount", v) if lg.kind == "amount" else display("date", v) if lg.kind == "date"
                            else (None if is_blank(v) else str(v)))
            cells[c] = cell
        ref = lg.ref
        retenu = cells[ref]["value"] if ref else None
        if lg.key == "plafond":
            caps = {c: parse_amount(cells[c]["value"]) for c in CAP_CONTROL if cells[c]["value"] is not None}
            for c, cap in caps.items():
                if montant is not None and cap is not None and montant > cap + 1.0:
                    cells[c]["issues"].append(("bloq", f"OV {display('amount', montant)} > plafond {display('amount', cap)}"))
            retenu = sy.get("PLAFOND_RETENU")
            lim = sy.get("PLAFOND_LIMITANT")
            ref = next((c for c, lab in (("ANNEXE_II", "Annexe II"), ("BULLETIN", "95% net"),
                                         ("PLANNING", "DOM période"), ("ATF", "ATF"),
                                         ("AUTORISATION", "Autorisation")) if lab == lim), "")
            for c, code in CAP_CONTROL.items():
                if code in nc and cells[c]["present"] and cells[c]["value"] is None:
                    cells[c]["issues"].append(("verif", str(nc[code]["DETAIL"])))
        else:
            for c, cell in cells.items():
                if not lg.compare or c == ref or cell["value"] is None or retenu is None:
                    continue
                ok, why = _same_ov(lg.kind, cell["value"], retenu)
                if lg.kind == "name":
                    sim = name_similarity(cell["value"], retenu)
                    ok = None if sim is None else sim >= seuil_nom
                    why = "" if sim is None else f"similarité {sim:.0%}"
                if ok is False:
                    cell["issues"].append(("incoh", f"Différent de {COL_LABEL[ref]} ({retenu})" + (f" — {why}" if why else "")))
            for code in lg.controls:
                if code in ko and lg.key in ("montant", "lettres"):
                    cells["OV"]["issues"].append(("bloq", str(ko[code]["DETAIL"])))
                if code in ("T02",) and cells["OV"]["value"] is None and cells["OV"]["present"]:
                    cells["OV"]["issues"].append(("verif", "Mention non lue"))
            if lg.key == "periode" and "T04" in ko:
                cells["PLANNING"]["issues"].append(("bloq", str(ko["T04"]["DETAIL"])))
            if lg.key == "devise" and "T17" in ko:
                cells["OV"]["issues"].append(("verif", str(ko["T17"]["DETAIL"])))
        for cell in cells.values():
            cell["open"] = bool(cell["issues"])
            cell["bloq"] = any(k == "bloq" for k, _ in cell["issues"])
        opens = [c for c in cells.values() if c["open"]]
        coh = "✗ bloquant" if any(c["bloq"] for c in opens) else ("✗ écart" if any(
            k == "incoh" for c in opens for k, _ in c["issues"]) else ("à vérifier" if opens else "✓"))
        rows.append({"ligne": lg, "cells": cells, "ref": ref, "retenu": retenu,
                     "retenu_txt": display("amount", retenu) if lg.kind == "amount" else (None if is_blank(retenu)
                                                                                           else str(retenu)),
                     "coh": coh, "n_open": len(opens)})
    dossier_ctl = ch[ch["CODE"].isin(DOSSIER_CONTROLS)] if not ch.empty else ch
    return {"fichier": fichier, "rows": rows, "sy": sy, "pl": pl, "checks": ch, "dossier_checks": dossier_ctl,
            "n_open": sum(r["n_open"] for r in rows)}


def list_frame(sy: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Liste des dossiers OV (1 ligne par dossier) pour l'écran principal."""
    if sy.empty:
        return pd.DataFrame()
    dec = decisions.drop_duplicates("FICHIER", keep="last").set_index("FICHIER") if not decisions.empty else None
    out = []
    for _, r in sy.iterrows():
        f = r["FICHIER"]
        dd = dec.loc[f] if dec is not None and f in dec.index else None
        decision = (dd["DECISION"] if dd is not None and not is_blank(dd["DECISION"]) else "")
        marge = r.get("MARGE")
        out.append({
            "FICHIER": f, "FEU": FEU.get(r["STATUT_CONTROLE"], "o"), "NOM": r.get("NOM"),
            "IDENTIFIANT_CLIENT": r.get("SIEGE_RACINE"), "PERIODE": r.get("PERIODE_TL"),
            "MONTANT": r.get("MONTANT_OV"), "PLAFOND": r.get("PLAFOND_RETENU"), "LIMITANT": r.get("PLAFOND_LIMITANT"),
            "MARGE": marge, "BLOQUANTS": int(r.get("NB_BLOQUANT") or 0), "A_REVOIR": int(r.get("NB_REVIEW") or 0),
            "STATUT_CONTROLE": r["STATUT_CONTROLE"], "DECISION": decision,
            "RATTACHE": not is_blank(r.get("PERIODE_ID")), "MOTIFS": r.get("MOTIFS"),
        })
    return pd.DataFrame(out)


def sample(fichiers: list[str], seed: str, pct: float = 0.05, minimum: int = 3) -> list[str]:
    """Échantillon de contrôle visuel avant validation en masse (reproductible pour un lot)."""
    if not fichiers:
        return []
    k = min(len(fichiers), max(minimum, round(len(fichiers) * pct)))
    return sorted(random.Random(seed).sample(sorted(fichiers), k))
