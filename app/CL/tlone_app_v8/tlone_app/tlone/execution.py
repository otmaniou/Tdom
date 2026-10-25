"""TL à exécuter : TL saisis dans CarthagoTrade et pas encore débités dans Atlas.

Règle : tout TL présent dans « Transfert libre -… » (hors rejetés) et absent de « Historique_mouvement_altas-… »
est un TL saisi par l'agence et non encore exécuté. Pour chacun, l'app vérifie :
  * doublon : même client + même période qu'un autre TL en attente ou déjà exécuté (mois complet ↔ P1/P2 inclus ;
    P1 et P2 du même mois ne sont pas un doublon) ;
  * dossier scanné et validé dans TL-One (OV + Annexe I + Annexe II + bulletin, contrôles T01–T17) ;
  * domiciliation (Planning), ATF, autorisation, plafonds — d'après les contrôles du dossier OV ;
  * vigilance RAS ou HIT levé ;
  * blocage des fonds, sans attendre la conformité (salaire perçu = solde suffisant, OV déposé) : blocage existant
    suffisant s'il dépasse le montant OV d'au moins 3 700 DZD ; sinon nouveau blocage = OV arrondi au millier
    inférieur + 5 000 DZD (690 231,17 -> 695 000), du plus ancien au plus récent tant que le solde le permet.
Statut : A_EXECUTER (tout est conforme et bloqué) · A_BLOQUER (conforme, blocage à faire, solde suffisant) ·
COMPLEMENT (pièce ou contrôle manquant, motifs listés) · DOUBLON · SOLDE_INSUFFISANT ·
ANOMALIE (« Exécuté » dans CarthagoTrade sans débit Atlas : ni exécuté, ni en cours).
Seul un débit Atlas fait foi d'exécution.
Le fichier de blocages pour l'agence ne contient que des blocages qui gardent le compte créditeur :
Solde_Dispo − Σ(blocages) ≥ 0, par client, en commençant par les périodes les plus anciennes.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from .common import is_blank, parse_amount
from . import historique as h

BLOCAGE_JOURS = 90
BLOCAGE_COLUMNS = ["SIEGE", "RACINE", "ORDINAL", "DEVISE", "REFERENCE DENOTAGE DU MOUVEMENT", "MT BLOCAGE DEV CPT",
                   "DATE DEBUT BLOCAGE", "DATE LIMITE BLOCAGE"]
# contrôles du dossier OV -> motif communiqué à l'agence / à l'employeur
MOTIF_CONTROLE = {
    "T01": "Pièce du dossier manquante", "T04": "Domiciliation absente ou période hors domiciliation",
    "T09": "Montant supérieur à la part transférable (Annexe II)", "T10": "Montant supérieur à 95 % du net",
    "T11": "Dépassement de la part domiciliée de la période", "T12": "ATF : travailleur absent ou montant dépassé",
    "T13": "Autorisation : absente ou montant dépassé", "T13b": "Autorisation échue",
    "T14": "TL déjà validé sur la période", "T15": "Cumul supérieur au montant domicilié",
    "T03": "Montant en chiffres ≠ montant en lettres", "T06": "Identité du travailleur à vérifier",
}
LIB_STATUT = {"A_EXECUTER": "Sera exécuté", "A_BLOQUER": "Sera exécuté après blocage des fonds",
              "COMPLEMENT": "En attente de complément", "DOUBLON": "TL en double — à annuler",
              "SOLDE_INSUFFISANT": "Solde insuffisant pour le blocage",
              "ANOMALIE": "Anomalie : « Exécuté » dans CarthagoTrade sans débit Atlas",
              "A_SAISIR": "OV reçu, TL à saisir par l'agence"}
LIB_BLOCAGE = {"OK": "✅ Bloqué", "A_BLOQUER": "🔒 À bloquer", "SOLDE_INSUFFISANT": "💰 Solde insuffisant",
               "SOLDE_INCONNU": "❔ Solde inconnu", "SANS_OBJET": "—"}
MOTIF_ANOMALIE = "Statut « Exécuté » dans CarthagoTrade mais aucun débit dans Atlas : à vérifier avec l'agence"


def _fr(x: float, dec: int = 2) -> str:
    """690231.17 -> '690 231,17'."""
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def denotage(periode: str | None) -> str | None:
    """'2026-06P1' -> '062026P1' (format des références de dénotage des blocages)."""
    if not periode or len(periode) < 7:
        return None
    return f"{periode[5:7]}{periode[:4]}{periode[7:]}"


def _conflit(a: dict, b: dict) -> bool:
    """Même client et même mois : conflit sauf P1 et P2 distincts."""
    if a["CLIENT"] != b["CLIENT"] or not a.get("MOIS") or a.get("MOIS") != b.get("MOIS"):
        return False
    ta, tb = [x if isinstance(x, str) and x else None for x in (a.get("TRANCHE"), b.get("TRANCHE"))]
    return not (ta and tb and ta != tb)


def _debites(atlas: pd.DataFrame | None) -> set:
    return set(atlas["REF_TL"].dropna()) if atlas is not None and not atlas.empty else set()


def etat_tl(trade: pd.DataFrame, atlas: pd.DataFrame | None) -> pd.Series:
    """EXECUTE (débit Atlas) · REJETE · ANOMALIE (« Exécuté » Trade sans débit Atlas) · EN_ATTENTE (saisi, non débité)."""
    deb = _debites(atlas)
    k = trade["STATUT_TRADE"].map(h._statut_key)
    return pd.Series(["EXECUTE" if r in deb else "REJETE" if s == "REJETE" else
                      "ANOMALIE" if s in h.EXECUTE and atlas is not None and not atlas.empty else "EN_ATTENTE"
                      for r, s in zip(trade["REF_TL"], k)], index=trade.index)


def pending(trade: pd.DataFrame, atlas: pd.DataFrame | None, anomalies: bool = False) -> pd.DataFrame:
    """TL saisis non débités (EN_ATTENTE) ; avec anomalies=True, aussi les « Exécuté » Trade sans débit Atlas."""
    if trade is None or trade.empty:
        return pd.DataFrame()
    t = trade.drop_duplicates("REF_TL")
    e = etat_tl(t, atlas)
    return t[e.isin({"EN_ATTENTE", "ANOMALIE"} if anomalies else {"EN_ATTENTE"})].assign(ETAT_TL=e).reset_index(drop=True)


def date_extraction(path) -> date | None:
    """Horodatage du nom d'export (« …-2026-10-20T13-05-44.xlsx ») -> date d'extraction."""
    import re
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})T", str(getattr(path, "name", path) or ""))
    try:
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None
    except ValueError:
        return None


def debut_blocage(files: dict) -> tuple[date, str]:
    """Début des blocages = J+1 de l'extraction (fichier des soldes, sinon Trade, sinon Atlas ; à défaut demain)."""
    for k in ("soldes", "trade", "atlas"):
        d = date_extraction(files.get(k)) if files.get(k) else None
        if d:
            return d + timedelta(days=1), f"J+1 de l'extraction {h.LABEL[k]} du {d:%d/%m/%Y}"
    return date.today() + timedelta(days=1), "J+1 d'aujourd'hui (aucune date d'extraction dans les noms de fichiers)"


def montant_blocage(montant_ov: float, majoration: float = 5000.0, arrondi: float = 1000.0) -> float:
    """Nouveau blocage : montant OV arrondi au millier inférieur + 5 000 DZD (690 231,17 -> 695 000)."""
    return float(math.floor(float(montant_ov) / arrondi) * arrondi + majoration) if arrondi else round(float(montant_ov) + majoration, 2)


def plan(trade: pd.DataFrame, atlas: pd.DataFrame | None, blocage: pd.DataFrame | None,
         soldes: pd.DataFrame | None, ov_synth: pd.DataFrame | None, ov_checks: pd.DataFrame | None,
         decisions: pd.DataFrame | None, vigilance: dict | None, majoration: float = 5000.0,
         tol: float = 1.0, planning: pd.DataFrame | None = None, marge_min: float = 3700.0,
         arrondi: float = 1000.0) -> pd.DataFrame:
    """Une ligne par TL en attente (et par OV déposé pas encore saisi dans CarthagoTrade), avec statut d'exécution,
    motifs, blocage existant et blocage à faire.

    Blocage (indépendant de la conformité : salaire perçu = solde suffisant, OV déposé) :
      * blocage existant suffisant s'il dépasse le montant OV d'au moins `marge_min` (3 700 DZD) ;
      * sinon nouveau blocage = montant OV arrondi au millier inférieur + `majoration` (5 000 DZD), moins l'existant ;
      * par client, des périodes les plus anciennes aux plus récentes, tant que le solde le permet."""
    pen_all = pending(trade, atlas, anomalies=True) if trade is not None and not trade.empty else pd.DataFrame()
    sy = ov_synth if ov_synth is not None else pd.DataFrame(columns=["FICHIER", "SIEGE_RACINE", "PERIODE_TL"])
    if pen_all.empty and sy.empty:
        return pd.DataFrame()
    anom = pen_all[pen_all["ETAT_TL"] == "ANOMALIE"] if not pen_all.empty else pen_all
    pen = pen_all[pen_all["ETAT_TL"] == "EN_ATTENTE"].reset_index(drop=True) if not pen_all.empty else pen_all
    t_all = trade.drop_duplicates("REF_TL") if trade is not None and not trade.empty else pd.DataFrame(columns=["REF_TL"])
    executes = t_all[t_all["REF_TL"].isin(_debites(atlas))]   # seul un débit Atlas fait foi
    # index (client, mois) : 12 000 TL exécutés et ~1 000 en attente sans comparaison deux à deux
    def _idx(df):
        out: dict = {}
        for x in df.to_dict("records"):
            out.setdefault((x.get("CLIENT"), x.get("MOIS")), []).append(x)
        return out
    i_pen, i_exe, i_ano = _idx(pen), _idx(executes), _idx(anom)
    ch = ov_checks if ov_checks is not None else pd.DataFrame(columns=["FICHIER", "CODE", "RESULTAT", "SEVERITE"])
    dec = (decisions.drop_duplicates("FICHIER", keep="last").set_index("FICHIER")["DECISION"].to_dict()
           if decisions is not None and not decisions.empty else {})
    vig = vigilance or {}
    bl = blocage.copy() if blocage is not None and not blocage.empty else pd.DataFrame(
        columns=["CLIENT", "PERIODE", "MONTANT_BLOCAGE", "DATE_LIMITE", "REFERENCE_DENOTAGE"])
    i_sy: dict = {}
    if not sy.empty:
        for i, (a_, b_) in enumerate(zip(sy["SIEGE_RACINE"].astype(str), sy["PERIODE_TL"].astype(str))):
            i_sy.setdefault((a_, b_), []).append(i)
    ko_par_fichier = ch[ch["RESULTAT"] == "KO"].groupby("FICHIER")["CODE"].apply(list).to_dict() if not ch.empty else {}
    ex_pm = _periode_index(planning) if planning is not None and not planning.empty else None

    def _blocage(client, periode, mt_ref, alertes):
        """(montant déjà bloqué, date limite, besoin ? , reste à bloquer, cible)"""
        b = bl[(bl["CLIENT"] == client) & (bl["PERIODE"] == periode)] if not bl.empty else bl
        bloque = float(b["MONTANT_BLOCAGE"].fillna(0).sum()) if not b.empty else 0.0
        lim = b["DATE_LIMITE"].dropna().max() if not b.empty else None
        if not b.empty and lim is not None and lim < date.today():
            alertes.append(f"Blocage échu le {lim:%d/%m/%Y} : à refaire")
            bloque = 0.0
        if mt_ref is None or mt_ref <= 0:
            return bloque, lim, False, 0.0, None
        if bloque + tol >= mt_ref + marge_min:
            return bloque, lim, False, 0.0, None
        cible = montant_blocage(mt_ref, majoration, arrondi)
        return bloque, lim, True, round(max(0.0, cible - bloque), 2), cible

    rows = []
    for _, r in pen.iterrows():
        d = r.to_dict()
        motifs, alertes = [], []
        # doublons
        k = (d.get("CLIENT"), d.get("MOIS"))
        autres = [x for x in i_pen.get(k, []) if x["REF_TL"] != d["REF_TL"]]
        dbl = [x["REF_TL"] for x in autres + i_exe.get(k, []) if _conflit(d, x)]
        if isinstance(d.get("COMPLEMENT"), str) and d["COMPLEMENT"]:
            # complément d'une période déjà exécutée : pas un doublon, dans la limite de la part de la période
            prec = [x for x in i_exe.get(k, []) if _conflit(d, x)]
            dbl = [x for x in dbl if x not in {p["REF_TL"] for p in prec}]
            if not prec:
                motifs.append("Complément annoncé mais aucun TL exécuté (débit Atlas) sur la période")
            elif ex_pm is not None:
                pr = rattacher_idx(ex_pm[0], ex_pm[1], d["CLIENT"], d.get("PERIODE"), d.get("MOIS"))
                deja = sum(float(p.get("MONTANT_TRADE") or 0) for p in prec)
                if pr is None:
                    motifs.append("Complément : période absente du Planning, part non contrôlable")
                elif deja + float(d.get("MONTANT_TRADE") or 0) > float(pr["MONTANT_MAX_THEORIQUE"]) + tol:
                    motifs.append(f"Complément : déjà transféré {deja:,.2f} + {float(d.get('MONTANT_TRADE') or 0):,.2f} "
                                  f"> part de la période {float(pr['MONTANT_MAX_THEORIQUE']):,.2f}")
        alerte = [x["REF_TL"] for x in i_ano.get(k, []) if _conflit(d, x)]
        if alerte:
            alertes.append(f"Même période que {', '.join(alerte)} (« Exécuté » Trade sans débit Atlas)")
        if d.get("STATUT_PERIODE") != "OK":
            motifs.append(f"Période de l'objet du transfert à préciser (« {d.get('OBJET')} »)")
        # dossier OV dans TL-One (même client, même période)
        cand = sy.iloc[i_sy.get((str(d["CLIENT"]), str(d["PERIODE"])), [])] if not sy.empty and d.get("PERIODE") else sy.iloc[0:0]
        fichier = cand["FICHIER"].iloc[0] if not cand.empty else None
        mt_ov = None
        if fichier is None:
            motifs.append("Dossier non scanné / non extrait dans TL-One (OV, Annexes, bulletin)")
        else:
            for code in ko_par_fichier.get(fichier, []):
                if code in MOTIF_CONTROLE:
                    motifs.append(MOTIF_CONTROLE[code])
            if dec.get(fichier) != "VALIDE":
                motifs.append("Dossier non validé dans TL-One" if dec.get(fichier) != "REJETE" else "Dossier rejeté dans TL-One")
            v = vig.get(fichier)
            if v not in ("RAS", "HIT_LEVE"):
                motifs.append({"HIT": "Vigilance : HIT à analyser", "HIT_CONFIRME": "Vigilance : alerte avérée",
                               "EN_ATTENTE": "Vigilance : retour attendu", "KO_A_REFAIRE": "Vigilance à refaire",
                               "A_VERIFIER": "Vigilance : résultat à vérifier"}.get(v, "Vigilance à faire"))
            mt_ov = cand["MONTANT_OV"].iloc[0] if "MONTANT_OV" in cand else None
            mt_ov = None if mt_ov is None or pd.isna(mt_ov) else float(mt_ov)
            if mt_ov is not None and d.get("MONTANT_TRADE") is not None \
                    and abs(mt_ov - float(d["MONTANT_TRADE"])) > tol:
                motifs.append(f"Montant Trade {d['MONTANT_TRADE']:,.2f} ≠ montant OV {mt_ov:,.2f}")
        # blocage : montant de l'OV déposé (à défaut celui de CarthagoTrade), sans attendre la conformité
        mt_ref = mt_ov if mt_ov else (float(d.get("MONTANT_TRADE") or 0) or None)
        bloque, lim, besoin, reste, cible = _blocage(d["CLIENT"], d.get("PERIODE"), mt_ref, alertes)
        rejete = fichier is not None and dec.get(fichier) == "REJETE"
        bloc = ("SANS_OBJET" if dbl or rejete or mt_ref is None else "A_BLOQUER" if besoin else "OK")
        statut = ("DOUBLON" if dbl else "COMPLEMENT" if motifs else "A_EXECUTER" if bloc == "OK" else "A_BLOQUER")
        rows.append({
            "REF_TL": d["REF_TL"], "CLIENT": d["CLIENT"], "NOM": d.get("NOM"), "PERIODE": d.get("PERIODE"),
            "OBJET": d.get("OBJET"), "MONTANT_TL": d.get("MONTANT_TRADE"), "MONTANT_OV": mt_ov,
            "STATUT_TRADE": d.get("STATUT_TRADE"),
            "DOSSIER_TLONE": fichier, "STATUT_VIGILANCE": vig.get(fichier) if fichier else None,
            "MONTANT_BLOQUE": round(bloque, 2), "DATE_LIMITE_BLOCAGE": lim, "MONTANT_A_BLOQUER": cible,
            "RESTE_A_BLOQUER": reste, "BLOCAGE": bloc, "DOUBLON_AVEC": ", ".join(dbl),
            "STATUT": statut, "MOTIFS": " | ".join(dict.fromkeys(motifs)), "ALERTE": " | ".join(alertes),
        })
    # OV déposés dans TL-One et pas encore saisis dans CarthagoTrade : blocage possible dès le dépôt
    if not sy.empty:
        connus = pen_all.to_dict("records") + executes.to_dict("records") if not pen_all.empty else executes.to_dict("records")
        idx_c = _idx(pd.DataFrame(connus)) if connus else {}
        for x in sy.to_dict("records"):
            per = str(x.get("PERIODE_TL") or "")
            if not per or per in ("nan", "None") or dec.get(x["FICHIER"]) == "REJETE":
                continue
            dd = {"CLIENT": str(x["SIEGE_RACINE"]), "MOIS": per[:7], "TRANCHE": per[7:] or None}
            if any(_conflit(dd, y) for y in idx_c.get((dd["CLIENT"], dd["MOIS"]), [])):
                continue
            mt = x.get("MONTANT_OV")
            mt = None if mt is None or pd.isna(mt) else float(mt)
            alertes = []
            bloque, lim, besoin, reste, cible = _blocage(dd["CLIENT"], per, mt, alertes)
            rows.append({"REF_TL": f"OV:{x['FICHIER']}", "CLIENT": dd["CLIENT"], "NOM": x.get("NOM"), "PERIODE": per,
                         "OBJET": denotage(per), "MONTANT_TL": None, "MONTANT_OV": mt, "STATUT_TRADE": "Non saisi",
                         "DOSSIER_TLONE": x["FICHIER"], "STATUT_VIGILANCE": vig.get(x["FICHIER"]),
                         "MONTANT_BLOQUE": round(bloque, 2), "DATE_LIMITE_BLOCAGE": lim, "MONTANT_A_BLOQUER": cible,
                         "RESTE_A_BLOQUER": reste, "BLOCAGE": ("A_BLOQUER" if besoin else "OK" if mt else "SANS_OBJET"),
                         "DOUBLON_AVEC": "", "STATUT": "A_SAISIR",
                         "MOTIFS": "OV déposé, TL à saisir par l'agence dans CarthagoTrade", "ALERTE": " | ".join(alertes)})
    for _, r in anom.iterrows():
        d = r.to_dict()
        rows.append({"REF_TL": d["REF_TL"], "CLIENT": d["CLIENT"], "NOM": d.get("NOM"), "PERIODE": d.get("PERIODE"),
                     "OBJET": d.get("OBJET"), "MONTANT_TL": d.get("MONTANT_TRADE"), "MONTANT_OV": None,
                     "STATUT_TRADE": d.get("STATUT_TRADE"),
                     "DOSSIER_TLONE": None, "STATUT_VIGILANCE": None, "MONTANT_BLOQUE": None, "DATE_LIMITE_BLOCAGE": None,
                     "MONTANT_A_BLOQUER": None, "RESTE_A_BLOQUER": None, "BLOCAGE": "SANS_OBJET", "DOUBLON_AVEC": "",
                     "STATUT": "ANOMALIE", "MOTIFS": MOTIF_ANOMALIE, "ALERTE": ""})
    out = pd.DataFrame(rows)
    return _apply_soldes(out, soldes)


def _apply_soldes(out: pd.DataFrame, soldes: pd.DataFrame | None) -> pd.DataFrame:
    """Blocages à faire, par client, des périodes les plus anciennes aux plus récentes : Solde_Dispo − Σ(à bloquer)
    ≥ 0 (le compte ne devient jamais débiteur). Au premier blocage qui ne passe pas, les suivants attendent."""
    out["SOLDE_DISPO"] = None
    out["SOLDE_APRES_BLOCAGE"] = None
    if out.empty:
        return out
    sol = {}
    if soldes is not None and not soldes.empty:
        s1 = soldes[soldes["ORDINAL"].fillna("001") == "001"] if "ORDINAL" in soldes else soldes
        sol = s1.groupby("CLIENT")["SOLDE_DISPO"].sum().to_dict()
    for cl, idx in out[out["BLOCAGE"] == "A_BLOQUER"].sort_values("PERIODE").groupby("CLIENT", sort=False).groups.items():
        dispo = sol.get(cl)
        bloque_avant = False
        for i in idx:
            out.at[i, "SOLDE_DISPO"] = dispo
            reste = float(out.at[i, "RESTE_A_BLOQUER"])
            if dispo is None:
                out.at[i, "BLOCAGE"] = "SOLDE_INCONNU"
                txt = "Solde du compte inconnu (fichier comptes_solde)"
            elif bloque_avant or dispo - reste < 0:
                out.at[i, "BLOCAGE"] = "SOLDE_INSUFFISANT"
                txt = (f"Solde disponible {_fr(dispo)} < blocage {_fr(reste)}" if not bloque_avant
                       else "Blocage d'une période plus ancienne en attente de solde")
                bloque_avant = True
            else:
                dispo -= reste
                out.at[i, "SOLDE_APRES_BLOCAGE"] = round(dispo, 2)
                continue
            if out.at[i, "STATUT"] == "A_BLOQUER":
                out.at[i, "STATUT"] = "SOLDE_INSUFFISANT"
            out.at[i, "MOTIFS"] = " | ".join(x for x in (out.at[i, "MOTIFS"], txt) if x)
    return out


def fichier_blocages(pl: pd.DataFrame, debut: date | None = None, jours: int = BLOCAGE_JOURS) -> pd.DataFrame:
    """Fichier à transmettre à l'agence : blocages à faire (OV déposé, conforme ou non), solde suffisant, du plus
    ancien au plus récent (format du fichier Blocage).
    `debut` = J+1 de l'extraction (voir debut_blocage) ; fin = début + 90 jours."""
    today = debut or date.today() + timedelta(days=1)
    if pl is None or pl.empty:
        return pd.DataFrame(columns=BLOCAGE_COLUMNS + ["REF_TL", "NOM"])
    col = "BLOCAGE" if "BLOCAGE" in pl else "STATUT"
    sel = pl[(pl[col] == "A_BLOQUER") & pl["SOLDE_APRES_BLOCAGE"].notna()].sort_values(["CLIENT", "PERIODE"])
    rows = [{"SIEGE": str(r.CLIENT)[:5], "RACINE": str(r.CLIENT)[5:11], "ORDINAL": "001", "DEVISE": "DZD",
             "REFERENCE DENOTAGE DU MOUVEMENT": denotage(r.PERIODE), "MT BLOCAGE DEV CPT": r.RESTE_A_BLOQUER,
             "DATE DEBUT BLOCAGE": today.strftime("%Y%m%d"),
             "DATE LIMITE BLOCAGE": (today + timedelta(days=jours)).strftime("%Y%m%d"),
             "REF_TL": r.REF_TL, "NOM": r.NOM} for r in sel.itertuples()]
    return pd.DataFrame(rows, columns=BLOCAGE_COLUMNS + ["REF_TL", "NOM"])


def fichier_employeur(pl: pd.DataFrame) -> pd.DataFrame:
    """Information de l'employeur : TL qui seront exécutés et TL en attente de complément (avec motifs)."""
    if pl is None or pl.empty:
        return pd.DataFrame()
    df = pl.assign(SITUATION=pl["STATUT"].map(LIB_STATUT))
    df = df.sort_values(["STATUT", "NOM", "PERIODE"])
    return df[["REF_TL", "NOM", "CLIENT", "PERIODE", "MONTANT_TL", "SITUATION", "MOTIFS", "DOUBLON_AVEC"]].rename(columns={
        "REF_TL": "Référence TL", "NOM": "Salarié", "CLIENT": "Identifiant client", "PERIODE": "Période",
        "MONTANT_TL": "Montant (DZD)", "SITUATION": "Situation", "MOTIFS": "Complément attendu / motif",
        "DOUBLON_AVEC": "En double avec"})


def _periode_index(planning: pd.DataFrame) -> tuple[dict, dict]:
    """(client, PERIODE_TL) -> ligne du Planning ; (client, mois) -> lignes du mois (mois partiel P1/P2)."""
    exact, par_mois = {}, {}
    cols = [c for c in ("SIEGE_RACINE", "PERIODE_TL", "MOIS_BASE", "PERIODE_ID", "DOM_ID", "NUMERO_DOMICILIATION",
                        "MONTANT_MAX_THEORIQUE", "DATE_FIN_APPLICABLE") if c in planning.columns]
    for r in planning[cols].to_dict("records"):
        cl = str(r.get("SIEGE_RACINE"))
        exact.setdefault((cl, str(r["PERIODE_TL"])), r)
        par_mois.setdefault((cl, str(r.get("MOIS_BASE") or str(r["PERIODE_TL"])[:7])), []).append(r)
    return exact, par_mois


def registre_atlas(planning: pd.DataFrame, trade: pd.DataFrame | None, atlas: pd.DataFrame | None) -> pd.DataFrame:
    """TL réellement exécutés (débit Atlas), au format du registre TL-One, rattachés aux périodes du Planning.
    Permet aux contrôles OV (T14 doublon de période, T15 cumul DOM) et au suivi du Planning de tenir compte de
    tout l'historique, y compris les TL antérieurs à TL-One (reliquats)."""
    from .transfers import REGISTRE_COLUMNS
    if trade is None or trade.empty or atlas is None or atlas.empty or planning is None or planning.empty:
        return pd.DataFrame(columns=REGISTRE_COLUMNS + ["REF_TL"])
    exact, par_mois = _periode_index(planning)
    at = atlas[atlas["REF_TL"].notna()]
    mt = at.assign(_A=pd.to_numeric(at["MONTANT_ATLAS"], errors="coerce").abs()).groupby("REF_TL")["_A"].sum()
    dt = pd.to_datetime(at["DATE_OPERATION"], errors="coerce").groupby(at["REF_TL"]).max().map(
        lambda x: None if pd.isna(x) else x.date())
    rows = []
    for r in trade.drop_duplicates("REF_TL").to_dict("records"):
        if r["REF_TL"] not in mt.index:
            continue
        pr = rattacher_idx(exact, par_mois, r["CLIENT"], r.get("PERIODE"), r.get("MOIS"))
        rows.append({"TL_ID": r["REF_TL"], "REF_TL": r["REF_TL"], "FICHIER": f"ATLAS:{r['REF_TL']}",
                     "DOM_ID": pr.get("DOM_ID") if pr else None, "PERIODE_ID": pr.get("PERIODE_ID") if pr else None,
                     "PERIODE_TL": r.get("PERIODE"), "SIEGE_RACINE": r["CLIENT"], "NOM": r.get("NOM"),
                     "NUMERO_DOMICILIATION": pr.get("NUMERO_DOMICILIATION") if pr else None,
                     "MONTANT": mt[r["REF_TL"]] or r.get("MONTANT_TRADE"), "DEVISE": "DZD", "DECISION": "VALIDE",
                     "COMMENTAIRE": f"Exécuté (débit Atlas) — {r.get('OBJET')}", "VALIDE_PAR": "ATLAS",
                     "DATE_VALIDATION": (dt[r["REF_TL"]].isoformat() if isinstance(dt[r["REF_TL"]], date) else None),
                     "STATUT_EXECUTION": "EXECUTE_ATLAS"})
    return pd.DataFrame(rows, columns=REGISTRE_COLUMNS + ["REF_TL"])


def rattacher_idx(exact, par_mois, client, periode, mois=None):
    """Période du Planning d'un TL : même période, sinon le mois quand le Planning n'a qu'une ligne pour ce mois
    (TL « 2026-05 » sur un mois partiel 2026-05P2, ou TL P1 sur un mois complet)."""
    if is_blank(periode):
        return None
    r = exact.get((str(client), str(periode)))
    if r is None:
        cands = par_mois.get((str(client), str(mois or str(periode)[:7])), [])
        r = cands[0] if len(cands) == 1 else None
    return r


def registre_complet(registre: pd.DataFrame, hreg: pd.DataFrame, tol: float = 1.0) -> pd.DataFrame:
    """Registre TL-One + exécutions Atlas. Une ligne TL-One de même période et même montant qu'un débit Atlas
    est le même TL (déjà exécuté) : elle n'est pas comptée deux fois."""
    from .common import parse_amount
    if hreg is None or hreg.empty:
        return registre
    if registre is None or registre.empty:
        return hreg
    at = {(p, round(parse_amount(m) or 0)) for p, m in zip(hreg["PERIODE_ID"], hreg["MONTANT"]) if not is_blank(p)}
    keep = [not (not is_blank(p) and any((p, round(parse_amount(m) or 0) + d) in at for d in range(-int(tol), int(tol) + 1)))
            for p, m in zip(registre["PERIODE_ID"], registre["MONTANT"])]
    return pd.concat([registre[keep], hreg], ignore_index=True)


ETAT_PERIODE = {"TRANSFERE": "✅ Transféré", "PARTIEL": "◐ Partiel", "SAISI_EN_ATTENTE": "🕓 TL validé / saisi, non exécuté",
                "ANOMALIE_TRADE": "⚠️ « Exécuté » Trade sans débit Atlas", "NON_TRANSFERE": "🔴 Reliquat à régulariser",
                "A_VENIR": "· À venir"}


def suivi_planning(planning: pd.DataFrame, registre: pd.DataFrame, trade: pd.DataFrame | None,
                   atlas: pd.DataFrame | None, tol: float = 1.0, today: date | None = None) -> pd.DataFrame:
    """Planning complet, du début du contrat (CTS) à sa fin : pour chaque période, montant exécuté (Atlas +
    registre TL-One), reliquat, références TL exécutées / saisies / en anomalie."""
    from .transfers import consumption
    if planning is None or planning.empty:
        return pd.DataFrame()
    hreg = registre_atlas(planning, trade, atlas)
    cons = consumption(planning, registre_complet(registre, hreg, tol), today=today, tol=tol)
    # « transféré » = débit Atlas ; un TL seulement validé dans TL-One (registre) n'est pas encore exécuté
    deb = hreg.assign(_M=hreg["MONTANT"].map(parse_amount)).groupby("PERIODE_ID")["_M"].sum() if not hreg.empty else {}
    cons["MONTANT_EXECUTE_ATLAS"] = cons["PERIODE_ID"].map(lambda p: float(deb.get(p, 0) or 0)).round(2)
    exact, par_mois = _periode_index(planning)
    refs: dict[str, dict[str, list]] = {}
    if trade is not None and not trade.empty:
        t = trade.drop_duplicates("REF_TL")
        for r, e in zip(t.to_dict("records"), etat_tl(t, atlas)):
            if e == "REJETE":
                continue
            pr = rattacher_idx(exact, par_mois, r["CLIENT"], r.get("PERIODE"), r.get("MOIS"))
            if pr is not None:
                refs.setdefault(pr["PERIODE_ID"], {}).setdefault(e, []).append(r["REF_TL"])
    g = lambda pid, e: ", ".join(refs.get(pid, {}).get(e, []))  # noqa: E731
    cons["TL_EXECUTES"] = [g(p, "EXECUTE") for p in cons["PERIODE_ID"]]
    cons["TL_SAISIS"] = [g(p, "EN_ATTENTE") for p in cons["PERIODE_ID"]]
    cons["TL_ANOMALIE"] = [g(p, "ANOMALIE") for p in cons["PERIODE_ID"]]
    st = []
    for s0, sa, an, ex in zip(cons["STATUT_PERIODE"], cons["TL_SAISIS"], cons["TL_ANOMALIE"], cons["MONTANT_EXECUTE_ATLAS"]):
        if s0 in ("TRANSFERE", "PARTIEL") and ex <= tol and atlas is not None and not atlas.empty:
            st.append("SAISI_EN_ATTENTE")       # validé / saisi, pas encore débité dans Atlas
        elif s0 in ("NON_TRANSFERE", "A_VENIR", "PARTIEL") and an:
            st.append("ANOMALIE_TRADE")
        elif s0 in ("NON_TRANSFERE", "A_VENIR", "PARTIEL") and sa:
            st.append("SAISI_EN_ATTENTE")
        else:
            st.append(s0)
    cons["STATUT_PERIODE"] = st
    cons["RELIQUAT"] = cons["SOLDE_RESTANT"].where(cons["STATUT_PERIODE"].isin(
        ["NON_TRANSFERE", "PARTIEL", "SAISI_EN_ATTENTE", "ANOMALIE_TRADE"]), 0.0).clip(lower=0).round(2)
    return cons


def hors_planning(planning: pd.DataFrame, trade: pd.DataFrame) -> pd.DataFrame:
    """TL (non rejetés) dont la période n'existe pas dans le Planning du client."""
    if trade is None or trade.empty:
        return pd.DataFrame()
    t = trade.drop_duplicates("REF_TL")
    t = t[t["STATUT_TRADE"].map(h._statut_key) != "REJETE"]
    if planning is None or planning.empty:
        return t
    keys = set(zip(planning["SIEGE_RACINE"].astype(str), planning["PERIODE_TL"].astype(str)))
    return t[[not is_blank(p) and (c, p) not in keys for c, p in zip(t["CLIENT"], t["PERIODE"])]]
