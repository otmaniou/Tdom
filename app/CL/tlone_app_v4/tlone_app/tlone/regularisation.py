"""Régularisation de la base : chaque période du Planning (début → fin du contrat), avec ce qui s'est passé.

On réutilise tout l'historique disponible — TL exécutés (Atlas), TL saisis (CarthagoTrade), extractions OV passées
(audit_transferts), ATF et autorisations de chaque mois, base RH — non pour ré-exécuter, mais pour savoir :
  * période transférée : le TL exécuté respectait-il la part de la période, l'ATF et l'autorisation du mois ?
    (contrôle a posteriori, constats d'audit) ;
  * période non transférée (reliquat) : pourquoi ? dossier OV jamais scanné, OV rejeté, absent de l'ATF ou de
    l'autorisation, montant autorisé inférieur à la part, TL saisi puis rejeté… (motif de non-exécution).
Le motif retenu est le premier de la chaîne du processus qui a manqué ; tous les constats sont listés.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .common import digits, is_blank, norm_name, parse_amount, parse_date
from .periode import lire

MOTIFS = {
    "M01": "Dossier OV jamais scanné / extrait",
    "M02": "TL saisi puis rejeté dans CarthagoTrade",
    "M03": "Dossier OV rejeté dans TL-One",
    "M04": "Dossier OV extrait mais non validé (écart de contrôle ou décision en attente)",
    "M05": "Salarié absent de l'ATF du mois",
    "M06": "Montant ATF inférieur à la part de la période",
    "M07": "Salarié absent des autorisations du mois",
    "M08": "Montant autorisé inférieur à la part de la période",
    "M09": "Salarié absent de la base RH du mois",
    "M10": "« Exécuté » dans CarthagoTrade sans débit Atlas",
    "M11": "TL saisi, non exécuté",
    "M12": "Vigilance non levée (HIT, retour attendu ou à faire)",
    "M99": "Motif non déterminé (historique du mois incomplet)",
}
CONSTATS = {
    "A01": "Montant exécuté supérieur à la part de la période",
    "A02": "Exécuté sans ATF du mois",
    "A03": "Montant exécuté supérieur à l'ATF",
    "A04": "Exécuté sans autorisation du mois",
    "A05": "Montant exécuté supérieur à l'autorisation",
    "A06": "Période débitée plusieurs fois",
}


def audits_historiques(P) -> list[Path]:
    """Toutes les extractions OV : lot courant (transferts_out) et historique déposé (historique_ov)."""
    out = []
    for d in (P.tr_out, P.data_root / "historique_ov"):
        if d.exists():
            out += sorted(d.glob("audit_transferts_*.xlsx"))
    return out


def index_ov(paths: list[Path]) -> dict[tuple, list[dict]]:
    """(client, mois) -> dossiers OV extraits (fichier, période lue, montant, lot)."""
    from .transfers import periode_from_filename, read_audit_xlsx
    from .rh import rib_parts
    idx: dict[tuple, list[dict]] = {}
    for p in paths:
        try:
            a = read_audit_xlsx(p)
        except Exception:  # noqa: BLE001
            continue
        for r in a.to_dict("records"):
            f = str(r.get("fichier"))
            cl = (rib_parts(r.get("OV.compte_debiteur")) or rib_parts(r.get("ANNEXE_II.compte_bancaire")) or {}).get("CLIENT")
            if not cl:
                d = digits(Path(f).stem)
                cl = d[:11] if d.startswith("07310") and len(d) >= 11 else None
            per = lire(r.get("OV.reference_paiement") or r.get("OV.periode"))["mois"] or periode_from_filename(f)[0]
            if cl and per:
                lu = lire(r.get("OV.reference_paiement") or r.get("OV.periode"))
                pf = periode_from_filename(f)
                periode = lu["periode"] if lu["mois"] else (pf[0] + (pf[1] or "") if pf[0] else None)
                idx.setdefault((cl, per), []).append({"fichier": f, "montant": parse_amount(r.get("OV.montant_chiffres")),
                                                     "lot": p.name, "periode": periode})
    return idx


def _ref_index(ref: pd.DataFrame | None, montant_col: str, noms: dict) -> dict[tuple, float]:
    """(client, mois) -> montant (ATF ou autorisation) ; client par le compte, sinon par le nom du Planning."""
    out: dict[tuple, float] = {}
    if ref is None or ref.empty:
        return out
    from .rh import rib_parts
    for r in ref.to_dict("records"):
        m = r.get("_MOIS")
        if not m:
            continue
        cl = (rib_parts(r.get("_COMPTE")) or {}).get("CLIENT") or noms.get(norm_name(r.get("NOM_PRENOM")))
        if cl:
            out[(cl, m)] = out.get((cl, m), 0.0) + float(parse_amount(r.get(montant_col)) or 0)
    return out


def analyser(planning: pd.DataFrame, trade: pd.DataFrame | None, atlas: pd.DataFrame | None,
             registre: pd.DataFrame | None, ov_index: dict, atf: pd.DataFrame | None, aut: pd.DataFrame | None,
             rhdf: pd.DataFrame | None, decisions: pd.DataFrame | None = None, tol: float = 1.0,
             today: date | None = None, vigilance: dict | None = None) -> pd.DataFrame:
    from .execution import suivi_planning
    from . import historique as h
    today = today or date.today()
    if planning is None or planning.empty:
        return pd.DataFrame()
    sp = suivi_planning(planning, registre if registre is not None else pd.DataFrame(), trade, atlas, tol=tol, today=today)
    noms = {norm_name(n): str(c) for n, c in zip(planning["NOM_TRAVAILLEUR"], planning["SIEGE_RACINE"]) if not is_blank(n)}
    i_atf = _ref_index(atf, "MONTANT_TRANSFERABLE", noms)
    i_aut = _ref_index(aut, "MONTANT_AUTORISE", noms)
    mois_atf = {m for _, m in i_atf} | ({m for m in atf["_MOIS"].dropna()} if atf is not None and not atf.empty else set())
    mois_aut = {m for _, m in i_aut} | ({m for m in aut["_MOIS"].dropna()} if aut is not None and not aut.empty else set())
    rh_keys = set(zip(rhdf["CLIENT"], rhdf["MOIS"])) if rhdf is not None and not rhdf.empty else set()
    mois_rh = {m for _, m in rh_keys}
    dec = (decisions.drop_duplicates("FICHIER", keep="last").set_index("FICHIER")["DECISION"].to_dict()
           if decisions is not None and not decisions.empty else {})
    rejets: dict[tuple, list[str]] = {}
    debit_n: dict[tuple, int] = {}
    if trade is not None and not trade.empty:
        t = trade.drop_duplicates("REF_TL")
        for cl, m, st_, ref in zip(t["CLIENT"], t["MOIS"], t["STATUT_TRADE"].map(h._statut_key), t["REF_TL"]):
            if st_ == "REJETE":
                rejets.setdefault((cl, m), []).append(ref)
        if atlas is not None and not atlas.empty:
            deb = set(atlas["REF_TL"].dropna())
            for cl, m, ref in zip(t["CLIENT"], t["MOIS"], t["REF_TL"]):
                if ref in deb:
                    debit_n[(cl, m)] = debit_n.get((cl, m), 0) + 1
    rows = []
    for r in sp.to_dict("records"):
        cl, per = str(r["SIEGE_RACINE"]), str(r["PERIODE_TL"])
        mois = str(r.get("MOIS_BASE") or per[:7])
        fin = parse_date(r.get("DATE_FIN_SEGMENT"))
        part = float(parse_amount(r.get("MONTANT_MAX_THEORIQUE")) or 0)
        ex = float(r.get("MONTANT_EXECUTE_ATLAS") or 0)
        k = (cl, mois)
        ovs_mois = ov_index.get(k, [])
        # OV de la période (P1 / P2 distinguées) ; un OV sans partie couvre le mois
        ovs = [o for o in ovs_mois if o.get("periode") in (per, mois)] or \
              ([o for o in ovs_mois if not str(o.get("periode") or "")[7:]] if per[7:] else ovs_mois)
        motifs, constats = [], []
        etat = r["STATUT_PERIODE"]
        if etat in ("TRANSFERE", "PARTIEL") or ex > tol:
            if ex > part + tol:
                constats.append(("A01", f"{ex:,.2f} > {part:,.2f}"))
            if mois in mois_atf:
                if k not in i_atf:
                    constats.append(("A02", ""))
                elif ex > i_atf[k] + tol:
                    constats.append(("A03", f"{ex:,.2f} > ATF {i_atf[k]:,.2f}"))
            if mois in mois_aut:
                if k not in i_aut:
                    constats.append(("A04", ""))
                elif ex > i_aut[k] + tol:
                    constats.append(("A05", f"{ex:,.2f} > autorisation {i_aut[k]:,.2f}"))
            if debit_n.get(k, 0) > 1 and not per.endswith(("P1", "P2")):
                constats.append(("A06", f"{debit_n[k]} TL débités"))
        if etat in ("NON_TRANSFERE", "PARTIEL", "ANOMALIE_TRADE", "SAISI_EN_ATTENTE") and (fin is None or fin < today):
            if etat == "ANOMALIE_TRADE":
                motifs.append(("M10", r.get("TL_ANOMALIE") or ""))
            if etat == "SAISI_EN_ATTENTE":
                motifs.append(("M11", r.get("TL_SAISIS") or ""))
            if k in rejets:
                motifs.append(("M02", ", ".join(rejets[k])))
            if not ovs:
                motifs.append(("M01", ""))
            else:
                ds = [dec.get(o["fichier"]) for o in ovs]
                if "REJETE" in ds:
                    motifs.append(("M03", ", ".join(o["fichier"] for o in ovs)))
                elif "VALIDE" not in ds:
                    motifs.append(("M04", ", ".join(o["fichier"] for o in ovs)))
                else:
                    vg = [(vigilance or {}).get(o["fichier"]) for o, x in zip(ovs, ds) if x == "VALIDE"]
                    if vigilance is not None and not any(v in ("RAS", "HIT_LEVE") for v in vg):
                        motifs.append(("M12", ", ".join(str(v or "à faire") for v in vg)))
            if mois in mois_atf:
                if k not in i_atf:
                    motifs.append(("M05", ""))
                elif i_atf[k] + tol < part:
                    motifs.append(("M06", f"ATF {i_atf[k]:,.2f} < part {part:,.2f}"))
            if mois in mois_aut:
                if k not in i_aut:
                    motifs.append(("M07", ""))
                elif i_aut[k] + tol < part:
                    motifs.append(("M08", f"autorisation {i_aut[k]:,.2f} < part {part:,.2f}"))
            if mois in mois_rh and k not in rh_keys:
                motifs.append(("M09", ""))
            if not motifs:
                motifs.append(("M99", "ATF / autorisations / extractions OV de ce mois non chargés" if
                               mois not in mois_atf or mois not in mois_aut else ""))
        rows.append({
            "PERIODE_TL": per, "NOM_TRAVAILLEUR": r.get("NOM_TRAVAILLEUR"), "SIEGE_RACINE": cl,
            "NUMERO_DOMICILIATION": r.get("NUMERO_DOMICILIATION"), "PART_PERIODE": round(part, 2),
            "EXECUTE_ATLAS": round(ex, 2), "RELIQUAT": r.get("RELIQUAT"), "ETAT": etat,
            "TL_EXECUTES": r.get("TL_EXECUTES"), "TL_SAISIS": r.get("TL_SAISIS"),
            "OV_EXTRAITS": ", ".join(o["fichier"] for o in ovs),
            "ATF_MOIS": i_atf.get(k), "AUTORISATION_MOIS": i_aut.get(k),
            "MOTIF_PRINCIPAL": MOTIFS[motifs[0][0]] if motifs else "",
            "CODE_MOTIF": motifs[0][0] if motifs else "",
            "MOTIFS": " | ".join(f"{MOTIFS[c]}{' (' + x + ')' if x else ''}" for c, x in motifs),
            "CONSTATS": " | ".join(f"{CONSTATS[c]}{' (' + x + ')' if x else ''}" for c, x in constats),
        })
    return pd.DataFrame(rows)


def synthese(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Motif", "Périodes", "Reliquat (DZD)"])
    m = df[df["CODE_MOTIF"] != ""]
    g = m.groupby("MOTIF_PRINCIPAL").agg(Périodes=("PERIODE_TL", "count"), Reliquat=("RELIQUAT", "sum")).reset_index()
    return g.rename(columns={"MOTIF_PRINCIPAL": "Motif", "Reliquat": "Reliquat (DZD)"}).sort_values("Périodes", ascending=False)
