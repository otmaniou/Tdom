"""Fichiers finaux transmis au BOCI pour exécuter les TL conformes : Trade, DOM, Règlement.

Formats repris des modèles « Trade_final_BOCI », « DOM_BOCI_Final », « Reglement_FINAL_BOCI » (en-têtes, ordre
des colonnes, feuilles « valeur fix » / « VALEUR FIXE »). Les trois fichiers sont produits à partir d'UNE seule
ligne par TL : ils sont cohérents par construction (même montant, même période, même bénéficiaire…).
Le contrôle `verifier` s'applique aussi à des fichiers préparés à la main : il retrouve les écarts entre fichiers
et les valeurs fixes non respectées.

Sources de chaque valeur, par ordre de priorité (traçables dans la colonne SOURCES de la préparation) :
OV validé (base réglementaire du TL) > base RH (document source de l'employeur) > export CarthagoTrade
> Planning / CarthagoDom > référentiels BOCI (banques, correspondants).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .common import digits, is_blank, parse_amount, parse_date
from .periode import lire
from .rh import iban_clean, iban_ok, swift11, swift_ok
from .transfers import devise_transfert

TRADE_COLUMNS = ["Code client", "Référence", "Statut", "Etape en cours", "Utilisateur de destination", "Agence",
                 "Date demande", "Pli reçu niveau siège", "Montant", "Devise ordre de virement",
                 "Compte à débiter (Siège+ Racine+ Ordinal)", "Devise cible", "Reference denotage",
                 "Nature du transfert", "Type de transfert", "Objet du transfert", "Nature du compte", "Code CRDS",
                 "Date valeur", "Nom", "Adresse", "Référence prédom", "N° domiciliation",
                 "Nom/Raison sociale bénéficiaire", "Adresse bénéficiaire", "Pays du bénéficiaire",
                 "Compte bénéficiaire", "Nom banque bénéficiaire", "Code Swift", "Pays Banque Beneficiaire"]
DOM_COLUMNS = ["Numéro domiciliation", "Type opération", "Ope Nature Bp", "Identifient client", "Mode de réglement",
               "Date valeur", "Montant", "Devise", "Référence opération SI", "Domicilié", "Nature opération",
               "Tarif douanier", "Balance Payment Codification", "Domiciliation Expedition", "Cancelled",
               "Cancellation Date", "Documents Controlled", "Documents Controlled Date", "Date domiciliation",
               "Taux de change", "Devise contre-valeur", "Montant convertit", "Nom complet/Raison social", "Adresse",
               "Type client", "Nom/Raison social contre-partie", "Nom complet (Banque)", "Adresse contre-partie",
               "Nom", "Description"]
REG_COLUMNS = ["Service", "LOT COMPTABLE", "Code Operation", "Amount", "Currency", "Cours Devise", "Amount dzd",
               "Siege", "Racine", "Ord", "Clé", "Account Currency", "Monnaie", "Name CLIENT", "Beneficiary Name",
               "ADRESSE BEN", "pays", "Siege ben", "Racine ben", "Ord ben", "Clé ben", "Account ben Currency",
               "ref ben", "cde eco", "Transfer Object", "libelle extrait", "CHAMP 20", "CHAMP 71", "CODE BIC",
               "NUM CONTE BEN", "CorrespondantSiege", "CorrespondantRacine", "CorrespondantOrd", "CorrespondantCle",
               "Mode Envoi", "INTERMEDIAIRE FINAN", "comission banque", "Value Date", "DATE VAL", "DATE VAL1",
               "REF_DENO.", "forcage depassem", "fraisSiege", "fraisRacine", "fraisOrd", "fraisCle", "fraisMonnaie"]
SHEETS = {"trade": "Trade_Consolidé", "dom": "DOM", "reglement": "Reglement_Consolidé"}
COLUMNS = {"trade": TRADE_COLUMNS, "dom": DOM_COLUMNS, "reglement": REG_COLUMNS}
LABEL = {"trade": "Trade", "dom": "DOM", "reglement": "Règlement"}

# Feuilles « valeur fix » des modèles : toujours ces valeurs ("" = toujours vide)
FIXES = {
    "trade": {"Utilisateur de destination": "", "Pli reçu niveau siège": "Non", "Devise ordre de virement": "DZD",
              "Nature du transfert": "Tranfert International", "Type de transfert": "Salaire",
              "Nature du compte": "Dinar", "Code CRDS": "BOCI"},
    "dom": {"Type opération": "Prélèvement", "Ope Nature Bp": "Montant en dinars", "Mode de réglement": "TRL",
            "Devise": "DZD", "Domicilié": "Oui", "Nature opération": "Transfert de Salaire", "Tarif douanier": "",
            "Balance Payment Codification": "331", "Domiciliation Expedition": "", "Cancelled": "Non",
            "Cancellation Date": "", "Documents Controlled": "Non", "Documents Controlled Date": "",
            "Taux de change": "", "Montant convertit": "", "Type client": "Particuliers"},
    "reglement": {"Service": "51", "LOT COMPTABLE": "SF", "Code Operation": "TDZ", "Siege ben": "", "Racine ben": "",
                  "Ord ben": "", "Clé ben": "", "Account ben Currency": "", "cde eco": "09990", "CHAMP 71": "S",
                  "Mode Envoi": "S", "comission banque": "NON", "forcage depassem": "O", "fraisSiege": "",
                  "fraisRacine": "", "fraisOrd": "", "fraisCle": "", "fraisMonnaie": ""},
}
# Valeurs constantes dans les modèles mais absentes des feuilles « valeur fix » (écart = à vérifier)
CONSTANTES = {
    "trade": {"Statut": "En cours d'execution", "Etape en cours": "06.Dispatcher BOCI"},
    "dom": {},
    "reglement": {"Amount": "", "Cours Devise": "", "Account Currency": "DZD", "Monnaie": ""},
}
NUMERIC = {"trade": ["Montant"], "dom": ["Montant"], "reglement": ["Amount dzd"]}

# Référentiel BOCI par défaut (modifiable dans l'app : referentiels/boci_parametres.xlsx)
BANQUES = [  # BIC (6 premiers caractères : banque + pays) -> nom attendu, pays
    ("TEBUTR", "TEB/TURK EKONOMI BANK", "Turquie"), ("YAPITR", "YAPI VE KREDI BANKASI", "Turquie"),
    ("TCZBTR", "TURKIYE ZIRAAT BANKASI", "Turquie"), ("AKBKTR", "AKBANK", "Turquie"),
    ("ISBKTR", "TURKIYE IS BANKASI", "Turquie"), ("TGBATR", "TURKIYE GARANTI BANKASI", "Turquie"),
    ("HDFCIN", "HDFC BANK LTD", "Inde"), ("PUNBIN", "PUNJAB NATIONAL BANK", "Inde"), ("CNRBIN", "Canara Bank", "Inde"),
    ("SBININ", "STATE BANK OF INDIA", "Inde"), ("ICICIN", "ICICI BANK LIMITED", "Inde"),
]
CORRESPONDANTS = [("EUR", "09990", "600003", "020", "60")]   # devise -> compte correspondant (Siège, Racine, Ord, Clé)
INTERMEDIAIRES = [("HDFCIN", "EUR", "CHASDEFXXXX"), ("PUNBIN", "EUR", "DEUTDEFFXXX"), ("CNRBIN", "EUR", "BARCDEFFXXX")]
PAYS_ISO = {"TR": "Turquie", "IN": "Inde", "CN": "Chine", "DE": "Allemagne", "FR": "France", "IT": "Italie",
            "ES": "Espagne", "PT": "Portugal", "GB": "Royaume-Uni", "US": "États-Unis", "BE": "Belgique",
            "NL": "Pays-Bas", "CH": "Suisse", "AZ": "Azerbaïdjan", "EG": "Égypte", "TN": "Tunisie", "MA": "Maroc",
            "PK": "Pakistan", "BD": "Bangladesh", "PH": "Philippines", "KR": "Corée du Sud", "JP": "Japon",
            "UA": "Ukraine", "RU": "Russie", "UZ": "Ouzbékistan", "TM": "Turkménistan", "ID": "Indonésie",
            "VN": "Viêt Nam", "NP": "Népal", "LK": "Sri Lanka", "SY": "Syrie", "LB": "Liban", "JO": "Jordanie"}


# ----------------------------------------------------------------------------- paramètres (référentiel BOCI)
def params_path(P) -> Path:
    return P.referentiels_dir / "boci_parametres.xlsx"


def default_params() -> dict[str, pd.DataFrame]:
    return {
        "BANQUES": pd.DataFrame(BANQUES, columns=["BIC6", "NOM_BANQUE", "PAYS"]),
        "CORRESPONDANTS": pd.DataFrame(CORRESPONDANTS, columns=["DEVISE", "SIEGE", "RACINE", "ORD", "CLE"]),
        "INTERMEDIAIRES": pd.DataFrame(INTERMEDIAIRES, columns=["BIC6", "DEVISE", "BIC_INTERMEDIAIRE"]),
        "PAYS": pd.DataFrame(sorted(PAYS_ISO.items()), columns=["ISO2", "PAYS"]),
        "OPTIONS": pd.DataFrame([("DATE_VAL_DECALAGE_JOURS", "1"), ("OBJET_FORMAT", "MMAAAA")],
                                columns=["PARAMETRE", "VALEUR"]),
    }


def load_params(P) -> dict[str, pd.DataFrame]:
    out = default_params()
    p = params_path(P)
    if p.exists():
        try:
            for k, df in pd.read_excel(p, sheet_name=None, dtype=str).items():
                if k in out:
                    out[k] = df.fillna("")
        except Exception:  # noqa: BLE001
            pass
    return out


def _opt(params, k, default):
    o = params.get("OPTIONS")
    if o is None or o.empty:
        return default
    m = o[o["PARAMETRE"] == k]
    return m["VALEUR"].iloc[0] if not m.empty and str(m["VALEUR"].iloc[0]).strip() else default


# ----------------------------------------------------------------------------- formats
def periode_canon(v) -> str | None:
    return lire(v)["periode"] if not is_blank(v) else None


def mmaaaa(periode: str | None) -> str | None:
    """'2026-05P1' -> '052026P1' (objet du transfert, REF_DENO, dénotage des blocages)."""
    if not periode or len(periode) < 7:
        return None
    return f"{periode[5:7]}{periode[:4]}{periode[7:]}"


def fdate(d) -> str:
    d = parse_date(d) if not isinstance(d, date) else d
    return d.strftime("%d/%m/%Y") if d else ""


def compte_parts(v) -> dict:
    """RIB 20 chiffres (0270 + 16) ou compte 16 chiffres (+DZD) -> client, siège, racine, ordinal, clé, rib."""
    d = digits(v)
    if len(d) == 20:
        d16 = d[4:]
    elif len(d) == 16:
        d16 = d
    else:
        return {}
    rib = "0270" + d16
    return {"CLIENT": d16[:11], "SIEGE": d16[:5], "RACINE": d16[5:11], "ORDINAL": d16[11:14], "CLE": d16[14:16],
            "RIB": rib, "RIB_OK": int(rib[3:]) % 97 == 0, "COMPTE": f"{d16}DZD"}


def bank_info(params, swift: str) -> tuple[str | None, str | None]:
    b6 = (swift or "")[:6]
    df = params["BANQUES"]
    m = df[df["BIC6"].astype(str).str.upper() == b6]
    pays = PAYS_ISO.get((swift or "")[4:6])
    pays_tab = params.get("PAYS")
    if pays_tab is not None and not pays_tab.empty:
        mp = pays_tab[pays_tab["ISO2"] == (swift or "")[4:6]]
        pays = mp["PAYS"].iloc[0] if not mp.empty else pays
    if m.empty:
        return None, pays
    return m["NOM_BANQUE"].iloc[0], (m["PAYS"].iloc[0] or pays)


def correspondant(params, devise: str) -> dict:
    df = params["CORRESPONDANTS"]
    m = df[df["DEVISE"].astype(str).str.upper() == str(devise or "").upper()]
    if m.empty:
        return {}
    r = m.iloc[0]
    return {"CorrespondantSiege": str(r["SIEGE"]), "CorrespondantRacine": str(r["RACINE"]),
            "CorrespondantOrd": str(r["ORD"]), "CorrespondantCle": str(r["CLE"])}


def intermediaire(params, swift: str, devise: str) -> str:
    df = params["INTERMEDIAIRES"]
    m = df[(df["BIC6"].astype(str).str.upper() == (swift or "")[:6]) & (df["DEVISE"].astype(str).str.upper() == str(devise or "").upper())]
    return str(m["BIC_INTERMEDIAIRE"].iloc[0]) if not m.empty else ""


def pays_fr(v) -> str | None:
    if is_blank(v):
        return None
    s = str(v).strip()
    up = s.upper()
    for k, lab in PAYS_ISO.items():
        if up in (k, lab.upper()) or up.replace("É", "E") == lab.upper().replace("É", "E"):
            return lab
    return s.title()


# ----------------------------------------------------------------------------- préparation des lignes
def _first(*pairs):
    """Première valeur non vide parmi (source, valeur) -> (valeur, source)."""
    for src, v in pairs:
        if not is_blank(v) and str(v).strip():
            return v, src
    return None, None


def preparer(prets: pd.DataFrame, trade: pd.DataFrame | None, sy: pd.DataFrame | None, audit_df: pd.DataFrame | None,
             rhdf: pd.DataFrame | None, planning: pd.DataFrame | None, carthago_dom: pd.DataFrame | None,
             params: dict) -> pd.DataFrame:
    """Une ligne par TL prêt, toutes les valeurs des 3 fichiers, avec leur source et les points bloquants."""
    from . import rh as _rh
    tr = trade.drop_duplicates("REF_TL").set_index("REF_TL") if trade is not None and not trade.empty else pd.DataFrame()
    syi = sy.set_index("FICHIER") if sy is not None and not sy.empty else pd.DataFrame()
    au = audit_df.assign(_F=audit_df["fichier"].astype(str)).set_index("_F") if audit_df is not None and not audit_df.empty \
        else pd.DataFrame()
    rows = []
    for p in prets.to_dict("records"):
        ref = p["REF_TL"]
        t = tr.loc[ref].to_dict() if not tr.empty and ref in tr.index else {}
        f = p.get("DOSSIER_TLONE")
        o = syi.loc[f].to_dict() if f and not syi.empty and f in syi.index else {}
        a = au.loc[f].to_dict() if f and not au.empty and f in au.index else {}
        per = periode_canon(p.get("PERIODE")) or p.get("PERIODE")
        r, _ = _rh.match(rhdf, p.get("CLIENT"), (per or "")[:7] or None, (per or "")[7:] or None, p.get("NOM")) \
            if rhdf is not None and not rhdf.empty else (None, "")
        r = r or {}
        src = {}

        def pick(name, *pairs):
            v, s_ = _first(*pairs)
            src[name] = s_
            return v
        cp = {}
        for s_, v in (("OV", a.get("OV.compte_debiteur")), ("RH", r.get("RIB")), ("Trade", t.get("COMPTE_A_DEBITER"))):
            c = compte_parts(v)
            if c and c["RIB_OK"] and c["CLIENT"] == p["CLIENT"]:
                cp, src["compte"] = c, s_
                break
        devise = pick("devise", ("RH", r.get("DEVISE")), ("OV", devise_transfert(a.get("OV.devise_transfert"))),
                      ("Trade", t.get("DEVISE_CIBLE")))
        swift = swift11(pick("swift", ("OV", o.get("SWIFT") or a.get("OV.swift")), ("RH", r.get("SWIFT")), ("Trade", t.get("SWIFT"))) or "")
        nom_b, pays_b = bank_info(params, swift)
        iban = iban_clean(pick("iban", ("OV", o.get("BENEFICIAIRE_COMPTE") or a.get("OV.beneficiaire_compte")),
                               ("RH", r.get("IBAN")), ("Trade", t.get("COMPTE_BENEF"))) or "")
        dom = pick("dom", ("Trade", t.get("DOMICILIATION")), ("Planning", o.get("NUMERO_DOMICILIATION")))
        dom = (digits(dom) + "DZD") if dom else None
        ddom = None
        if dom and carthago_dom is not None and not carthago_dom.empty:
            m = carthago_dom[carthago_dom["_DOM"] == dom]
            if not m.empty:
                ddom, src["date_dom"] = m["_DATE"].iloc[0], "CarthagoDom"
        line = {
            "REF_TL": ref, "CLIENT": p["CLIENT"], "PERIODE": per, "MONTANT": parse_amount(p.get("MONTANT_TL")),
            "DEVISE": str(devise or "").upper() or None,
            "NOM_CLIENT": pick("nom_client", ("Trade", t.get("NOM")), ("RH", r.get("NOM_PRENOM")), ("OV", o.get("NOM"))),
            "NOM_CLIENT_RH": pick("nom_client_rh", ("RH", r.get("NOM_PRENOM")), ("Trade", t.get("NOM")), ("OV", o.get("NOM"))),
            "ADRESSE_CLIENT": pick("adresse_client", ("Trade", t.get("ADRESSE"))),
            "DATE_DEMANDE": pick("date_demande", ("Trade", t.get("DATE_DEMANDE_TRADE")), ("OV", o.get("DATE_DEMANDE"))),
            "PREDOM": pick("predom", ("Trade", t.get("PREDOM"))),
            "DOMICILIATION": dom, "DATE_DOMICILIATION": ddom,
            "BENEFICIAIRE": pick("beneficiaire", ("OV", o.get("BENEFICIAIRE")), ("RH", r.get("BENEFICIAIRE")),
                                 ("Trade", t.get("BENEFICIAIRE"))),
            "ADRESSE_BENEF": pick("adresse_benef", ("RH", r.get("ADRESSE_BENEF")), ("OV", a.get("OV.beneficiaire_adresse")),
                                  ("Trade", t.get("ADRESSE_BENEF"))),
            "IBAN": iban, "SWIFT": swift,
            "BANQUE": nom_b or pick("banque", ("RH", r.get("BANQUE_ETR")), ("OV", o.get("BANQUE")), ("Trade", t.get("BANQUE"))),
            "PAYS": pays_b or pays_fr(r.get("PAYS_BANQUE")) or pays_fr(t.get("PAYS_DESTINATION")),
            **{k: cp.get(k) for k in ("SIEGE", "RACINE", "ORDINAL", "CLE", "COMPTE", "RIB")},
            "DOSSIER_TLONE": f, "RH_MATRICULE": r.get("MATRICULE"),
        }
        bl = []
        for k, lab in (("COMPTE", "compte à débiter (RIB valide du client)"), ("DEVISE", "devise de transfert"),
                       ("PERIODE", "période"), ("DOMICILIATION", "n° de domiciliation"), ("BENEFICIAIRE", "bénéficiaire"),
                       ("ADRESSE_BENEF", "adresse du bénéficiaire"), ("IBAN", "compte du bénéficiaire"),
                       ("BANQUE", "banque du bénéficiaire"), ("NOM_CLIENT", "nom du client"), ("ADRESSE_CLIENT", "adresse du client"),
                       ("DATE_DEMANDE", "date de demande"), ("PREDOM", "référence prédom")):
            if is_blank(line.get(k)):
                bl.append(f"{lab} absent")
        if not line["MONTANT"]:
            bl.append("montant absent")
        if line["DEVISE"] and line["DEVISE"] not in ("USD", "EUR"):
            bl.append(f"devise {line['DEVISE']} inattendue")
        if not swift_ok(swift):
            bl.append(f"SWIFT invalide « {swift} »")
        if iban_ok(iban) is False:
            bl.append("IBAN invalide (clé)")
        warn = []
        if is_blank(ddom):
            warn.append("date de domiciliation à compléter (CarthagoDom)")
        if r and r.get("IBAN") and iban and r["IBAN"] != iban:
            warn.append("IBAN OV ≠ base RH")
        line["BLOQUANTS"] = " | ".join(bl)
        line["A_VERIFIER"] = " | ".join(warn)
        line["SOURCES"] = ", ".join(f"{k}={v}" for k, v in src.items() if v)
        rows.append(line)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- génération
def generer(lignes: pd.DataFrame, date_valeur: date | None = None, params: dict | None = None) -> dict[str, pd.DataFrame]:
    """date_valeur : None par défaut — le BOCI renseigne la date valeur (et DATE VAL / DATE VAL1) après la salle des
    marchés ; TL-One laisse ces colonnes vides."""
    params = params or default_params()
    dv = fdate(date_valeur) if date_valeur else ""
    dval = fdate(date_valeur - timedelta(days=int(_opt(params, "DATE_VAL_DECALAGE_JOURS", "1")))) if date_valeur else ""
    objet_fmt = _opt(params, "OBJET_FORMAT", "MMAAAA")
    T, D, R = [], [], []
    for l in lignes.to_dict("records"):
        per = l["PERIODE"]
        objet = mmaaaa(per) if objet_fmt == "MMAAAA" else per
        T.append({**{c: "" for c in TRADE_COLUMNS}, **FIXES["trade"], **CONSTANTES["trade"],
                  "Code client": l["CLIENT"], "Référence": l["REF_TL"], "Agence": f"BNP/{l['CLIENT'][:5]}",
                  "Date demande": fdate(l.get("DATE_DEMANDE")), "Montant": l["MONTANT"],
                  "Compte à débiter (Siège+ Racine+ Ordinal)": l["COMPTE"], "Devise cible": l["DEVISE"],
                  "Reference denotage": per, "Objet du transfert": objet, "Date valeur": dv,
                  "Nom": l["NOM_CLIENT"], "Adresse": l["ADRESSE_CLIENT"], "Référence prédom": l["PREDOM"],
                  "N° domiciliation": l["DOMICILIATION"], "Nom/Raison sociale bénéficiaire": l["BENEFICIAIRE"],
                  "Adresse bénéficiaire": l["ADRESSE_BENEF"], "Pays du bénéficiaire": l["PAYS"],
                  "Compte bénéficiaire": l["IBAN"], "Nom banque bénéficiaire": l["BANQUE"], "Code Swift": l["SWIFT"],
                  "Pays Banque Beneficiaire": l["PAYS"]})
        D.append({**{c: "" for c in DOM_COLUMNS}, **FIXES["dom"],
                  "Numéro domiciliation": l["DOMICILIATION"], "Identifient client": l["CLIENT"], "Date valeur": dv,
                  "Montant": l["MONTANT"], "Référence opération SI": l["REF_TL"],
                  "Date domiciliation": fdate(l.get("DATE_DOMICILIATION")), "Devise contre-valeur": l["DEVISE"],
                  "Nom complet/Raison social": l["NOM_CLIENT"], "Adresse": l["ADRESSE_CLIENT"],
                  "Nom/Raison social contre-partie": l["BENEFICIAIRE"], "Nom complet (Banque)": l["BANQUE"],
                  "Adresse contre-partie": l["ADRESSE_BENEF"], "Nom": l["PAYS"], "Description": f"Salaire {per}"})
        R.append({**{c: "" for c in REG_COLUMNS}, **FIXES["reglement"], **CONSTANTES["reglement"],
                  "Currency": l["DEVISE"], "Amount dzd": l["MONTANT"], "Siege": l["SIEGE"], "Racine": l["RACINE"],
                  "Ord": l["ORDINAL"], "Clé": l["CLE"], "Name CLIENT": l.get("NOM_CLIENT_RH") or l["NOM_CLIENT"],
                  "Beneficiary Name": l["BENEFICIAIRE"], "ADRESSE BEN": l["ADRESSE_BENEF"], "pays": l["PAYS"],
                  "ref ben": l["BENEFICIAIRE"], "Transfer Object": f"SALAIRE {per}", "libelle extrait": l["REF_TL"],
                  "CHAMP 20": l["REF_TL"], "CODE BIC": l["SWIFT"], "NUM CONTE BEN": l["IBAN"],
                  **correspondant(params, l["DEVISE"]), "INTERMEDIAIRE FINAN": intermediaire(params, l["SWIFT"], l["DEVISE"]),
                  "Value Date": dv, "DATE VAL": dval, "DATE VAL1": dv, "REF_DENO.": mmaaaa(per)})
    return {"trade": pd.DataFrame(T, columns=TRADE_COLUMNS), "dom": pd.DataFrame(D, columns=DOM_COLUMNS),
            "reglement": pd.DataFrame(R, columns=REG_COLUMNS)}


def file_names(n: int, now: datetime | None = None) -> dict[str, str]:
    st = (now or datetime.now()).strftime("%Y%m%dT%H%M%S")
    return {"trade": f"Trade_final_BOCI_{st}.xlsx", "dom": f"DOM_BOCI_Final-{st}.xlsx",
            "reglement": f"Reglement_FINAL_BOCI_{n}TL_{st}.xlsx"}


def to_xlsx(kind: str, df: pd.DataFrame) -> bytes:
    """Classeur au format du modèle : codes en texte (zéros de tête conservés), montants numériques #,##0.00."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = SHEETS[kind]
    ws.append(list(df.columns))
    for c in ws[1]:
        c.font = Font(bold=True)
    num = set(NUMERIC[kind])
    for row in df.itertuples(index=False):
        vals = []
        for col, v in zip(df.columns, row):
            if col in num:
                vals.append(float(v) if not is_blank(v) else None)
            else:
                vals.append(None if is_blank(v) or str(v) == "" else str(v))
        ws.append(vals)
    for col_idx, col in enumerate(df.columns, start=1):
        for cell in ws.iter_cols(min_col=col_idx, max_col=col_idx, min_row=2):
            for c in cell:
                c.number_format = "#,##0.00" if col in num else "@"
        ws.column_dimensions[ws.cell(1, col_idx).column_letter].width = max(10, min(45, len(col) + 4))
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ----------------------------------------------------------------------------- contrôle des fichiers
def read_file(path_or_bytes, kind: str | None = None) -> tuple[str | None, pd.DataFrame]:
    """Lit un fichier BOCI (première feuille de données) ; type reconnu par ses colonnes."""
    from io import BytesIO
    src = BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    sheets = pd.read_excel(src, sheet_name=None, dtype=str)
    best = None
    for name, df in sheets.items():
        cols = [str(c).strip() for c in df.columns]
        for k, ref in COLUMNS.items():
            score = len(set(cols) & set(ref)) / len(ref)
            if score >= 0.6 and (best is None or score > best[0]):
                best = (score, k, df)
    if best is None:
        return None, pd.DataFrame()
    _, k, df = best
    df.columns = [str(c).strip() for c in df.columns]
    return kind or k, df.fillna("")


def _s(v) -> str:
    return "" if is_blank(v) else str(v).strip()


def _num(v):
    return parse_amount(v)


def verifier(files: dict[str, pd.DataFrame], params: dict | None = None, planning: pd.DataFrame | None = None,
             tol: float = 0.01) -> pd.DataFrame:
    """Anomalies des fichiers Trade / DOM / Règlement : structure, valeurs fixes, formats et cohérence entre
    fichiers pour chaque TL. NIVEAU : BLOQUANT (à corriger avant envoi) ou A_VERIFIER."""
    params = params or default_params()
    an: list[dict] = []

    def add(niv, code, txt, ref=None, fichier=None, col=None, val=None, att=None):
        an.append({"NIVEAU": niv, "CODE": code, "REF_TL": ref, "FICHIER": fichier, "COLONNE": col,
                   "VALEUR": val, "ATTENDU": att, "ANOMALIE": txt})
    keycol = {"trade": "Référence", "dom": "Référence opération SI", "reglement": "CHAMP 20"}
    by: dict[str, dict] = {}
    for k, df in files.items():
        if df is None or df.empty:
            continue
        lab = LABEL[k]
        miss = [c for c in COLUMNS[k] if c not in df.columns]
        if miss:
            add("BLOQUANT", "B01", f"Colonnes absentes : {', '.join(miss)}", fichier=lab)
        extra = [c for c in df.columns if c not in COLUMNS[k] and not str(c).startswith("Unnamed")]
        if extra:
            add("A_VERIFIER", "B02", f"Colonnes en trop : {', '.join(extra)}", fichier=lab)
        if not miss and list(df.columns[:len(COLUMNS[k])]) != COLUMNS[k]:
            add("A_VERIFIER", "B03", "Ordre des colonnes différent du modèle", fichier=lab)
        kc = keycol[k]
        if kc not in df.columns:
            continue
        dups = df[kc][df[kc].duplicated(keep=False) & (df[kc] != "")]
        for ref in sorted(set(dups)):
            add("BLOQUANT", "B04", "Référence TL en double dans le fichier", ref, lab)
        for i, r in df.iterrows():
            ref = _s(r.get(kc)) or f"ligne {i + 2}"
            for col, att in FIXES[k].items():
                if col in df.columns and _s(r.get(col)) != att:
                    add("BLOQUANT", "B05", "Valeur fixe non respectée", ref, lab, col, _s(r.get(col)), att or "(vide)")
            for col, att in CONSTANTES[k].items():
                if col in df.columns and _s(r.get(col)) != att:
                    add("A_VERIFIER", "B06", "Valeur différente des autres TL du modèle", ref, lab, col, _s(r.get(col)), att or "(vide)")
            by.setdefault(ref, {})[k] = r.to_dict()
    # ---- cohérence par TL entre les 3 fichiers
    present = [k for k in files if files[k] is not None and not files[k].empty]
    dvs = set()
    clients_periodes: dict[tuple, list] = {}
    dom_dates: dict[str, set] = {}
    for ref, f in by.items():
        for k in present:
            if k not in f:
                add("BLOQUANT", "C01", f"TL absent du fichier {LABEL[k]}", ref, LABEL[k])
        t, d, g = f.get("trade", {}), f.get("dom", {}), f.get("reglement", {})

        def same(code, txt, vals: dict, norm=_s, niveau="BLOQUANT", prefix_ok=False):
            v = {lab: norm(x) for lab, x in vals.items() if _s(x)}
            u = set(v.values())
            if len(u) > 1:
                if prefix_ok:
                    vs = sorted(u, key=len)
                    if all(vs[-1].startswith(x) for x in vs):
                        add("A_VERIFIER", code, txt + " (troncature)", ref, " / ".join(v), val=" | ".join(f"{a}: {b}" for a, b in v.items()))
                        return
                add(niveau, code, txt, ref, " / ".join(v), val=" | ".join(f"{a}: {b}" for a, b in v.items()))
        same("C02", "Montant différent", {"Trade": t.get("Montant"), "DOM": d.get("Montant"), "Règlement": g.get("Amount dzd")},
             lambda x: f"{_num(x):.2f}" if _num(x) is not None else _s(x))
        cl_reg = (_s(g.get("Siege")) + _s(g.get("Racine"))) if g else ""
        same("C03", "Client différent", {"Trade": t.get("Code client"), "DOM": d.get("Identifient client"), "Règlement": cl_reg})
        same("C04", "Devise différente", {"Trade": t.get("Devise cible"), "DOM": d.get("Devise contre-valeur"), "Règlement": g.get("Currency")},
             lambda x: _s(x).upper())
        pers = {"Trade réf. dénotage": t.get("Reference denotage"), "Trade objet": t.get("Objet du transfert"),
                "DOM description": d.get("Description"), "Règlement objet": g.get("Transfer Object"),
                "Règlement REF_DENO": g.get("REF_DENO.")}
        same("C05", "Période différente entre fichiers", pers, lambda x: periode_canon(x) or _s(x))
        if t.get("Reference denotage") and not re.fullmatch(r"\d{4}-\d{2}(P[12])?", _s(t.get("Reference denotage"))):
            add("A_VERIFIER", "F01", "Format de la référence de dénotage Trade (AAAA-MM[P1|P2] attendu)", ref, "Trade",
                "Reference denotage", _s(t.get("Reference denotage")))
        fmt = _opt(params, "OBJET_FORMAT", "MMAAAA")
        ob = _s(t.get("Objet du transfert"))
        if ob and not re.fullmatch(r"\d{6}(P[12])?" if fmt == "MMAAAA" else r"\d{4}-\d{2}(P[12])?", ob):
            add("A_VERIFIER", "F11", f"Format de l'objet du transfert ({'MMAAAA' if fmt == 'MMAAAA' else 'AAAA-MM'}[P1|P2] attendu)",
                ref, "Trade", "Objet du transfert", ob)
        if g.get("REF_DENO.") and not re.fullmatch(r"\d{6}(P[12])?", _s(g.get("REF_DENO."))) or \
                (g.get("REF_DENO.") and re.fullmatch(r"20\d{4}(P[12])?", _s(g.get("REF_DENO.")))):
            add("A_VERIFIER", "F02", "Format REF_DENO (MMAAAA[P1|P2] attendu)", ref, "Règlement", "REF_DENO.", _s(g.get("REF_DENO.")))
        for lab, x in (("Trade", t.get("Date valeur")), ("DOM", d.get("Date valeur")), ("Règlement", g.get("Value Date")),
                       ("Règlement DATE VAL1", g.get("DATE VAL1"))):
            if _s(x):
                dvs.add(_s(x))
        same("C06", "Date valeur différente", {"Trade": t.get("Date valeur"), "DOM": d.get("Date valeur"),
                                                "Règlement": g.get("Value Date"), "Règlement DATE VAL1": g.get("DATE VAL1")})
        dv, dval = parse_date(g.get("Value Date")), parse_date(g.get("DATE VAL"))
        if dv and dval and dval != dv - timedelta(days=int(_opt(params, "DATE_VAL_DECALAGE_JOURS", "1"))):
            add("A_VERIFIER", "C07", "DATE VAL ≠ date valeur − 1 jour", ref, "Règlement", "DATE VAL", _s(g.get("DATE VAL")))
        same("C08", "Bénéficiaire différent", {"Trade": t.get("Nom/Raison sociale bénéficiaire"),
                                               "DOM": d.get("Nom/Raison social contre-partie"),
                                               "Règlement": g.get("Beneficiary Name"), "Règlement ref ben": g.get("ref ben")},
             lambda x: _s(x).upper())
        same("C09", "Compte du bénéficiaire différent", {"Trade": t.get("Compte bénéficiaire"), "Règlement": g.get("NUM CONTE BEN")},
             iban_clean)
        iban = iban_clean(t.get("Compte bénéficiaire") or g.get("NUM CONTE BEN"))
        if iban_ok(iban) is False:
            add("BLOQUANT", "F03", "IBAN invalide (longueur ou clé de contrôle)", ref, "Trade", "Compte bénéficiaire", iban)
        if _s(t.get("Compte bénéficiaire")) and _s(t.get("Compte bénéficiaire")) != iban:
            add("A_VERIFIER", "F04", "Compte bénéficiaire avec espaces / minuscules", ref, "Trade", "Compte bénéficiaire",
                _s(t.get("Compte bénéficiaire")), iban)
        same("C10", "SWIFT différent", {"Trade": t.get("Code Swift"), "Règlement": g.get("CODE BIC")}, lambda x: swift11(x))
        for lab, x in (("Trade", t.get("Code Swift")), ("Règlement", g.get("CODE BIC"))):
            if _s(x) and (len(_s(x)) != 11 or not swift_ok(x)):
                add("BLOQUANT", "F05", "SWIFT sur 11 caractères attendu", ref, lab, "Code Swift" if lab == "Trade" else "CODE BIC", _s(x), swift11(x))
        same("C11", "Adresse du bénéficiaire différente", {"Trade": t.get("Adresse bénéficiaire"), "DOM": d.get("Adresse contre-partie"),
                                                           "Règlement": g.get("ADRESSE BEN")},
             lambda x: re.sub(r"\s+", " ", _s(x).upper()), niveau="A_VERIFIER", prefix_ok=True)
        same("C12", "Banque différente", {"Trade": t.get("Nom banque bénéficiaire"), "DOM": d.get("Nom complet (Banque)")},
             lambda x: _s(x).upper(), niveau="A_VERIFIER")
        sw = swift11(t.get("Code Swift") or g.get("CODE BIC"))
        nb, pb = bank_info(params, sw)
        if nb and _s(t.get("Nom banque bénéficiaire")) and _s(t.get("Nom banque bénéficiaire")).upper() != nb.upper():
            add("A_VERIFIER", "F06", "Nom de banque ≠ référentiel BIC", ref, "Trade", "Nom banque bénéficiaire",
                _s(t.get("Nom banque bénéficiaire")), nb)
        same("C13", "Nom du client différent", {"Trade": t.get("Nom"), "DOM": d.get("Nom complet/Raison social")},
             lambda x: _s(x).upper(), niveau="A_VERIFIER")
        same("C14", "N° de domiciliation différent", {"Trade": t.get("N° domiciliation"), "DOM": d.get("Numéro domiciliation")})
        same("C15", "Pays différent", {"Trade bénéficiaire": t.get("Pays du bénéficiaire"), "Trade banque": t.get("Pays Banque Beneficiaire"),
                                       "DOM": d.get("Nom"), "Règlement": g.get("pays")}, lambda x: _s(x).upper(), niveau="A_VERIFIER")
        # compte à débiter : RIB du client (clé Modulo 97) et cohérence Trade / Règlement
        cp = compte_parts(t.get("Compte à débiter (Siège+ Racine+ Ordinal)"))
        if t and not cp:
            add("BLOQUANT", "F07", "Compte à débiter illisible (16 chiffres + DZD attendus)", ref, "Trade",
                "Compte à débiter (Siège+ Racine+ Ordinal)", _s(t.get("Compte à débiter (Siège+ Racine+ Ordinal)")))
        elif cp:
            if not cp["RIB_OK"]:
                add("BLOQUANT", "F08", "Clé du compte à débiter invalide (Modulo 97)", ref, "Trade",
                    "Compte à débiter (Siège+ Racine+ Ordinal)", cp["COMPTE"])
            if _s(t.get("Code client")) and cp["CLIENT"] != _s(t.get("Code client")):
                add("BLOQUANT", "F09", "Compte à débiter d'un autre client", ref, "Trade", "Compte à débiter (Siège+ Racine+ Ordinal)",
                    cp["COMPTE"], _s(t.get("Code client")))
            if g and (cp["ORDINAL"], cp["CLE"]) != (_s(g.get("Ord")), _s(g.get("Clé"))):
                add("BLOQUANT", "C16", "Ordinal / clé différents Trade / Règlement", ref, "Trade / Règlement",
                    val=f"Trade {cp['ORDINAL']}/{cp['CLE']} | Règlement {_s(g.get('Ord'))}/{_s(g.get('Clé'))}")
        if t and _s(t.get("Agence")) and _s(t.get("Code client")) and _s(t.get("Agence")) != f"BNP/{_s(t.get('Code client'))[:5]}":
            add("A_VERIFIER", "F10", "Agence ≠ BNP/<siège du client>", ref, "Trade", "Agence", _s(t.get("Agence")),
                f"BNP/{_s(t.get('Code client'))[:5]}")
        # correspondant / intermédiaire selon la devise
        if g:
            dev = _s(g.get("Currency")).upper()
            att = correspondant(params, dev)
            got = {k: _s(g.get(k)) for k in ("CorrespondantSiege", "CorrespondantRacine", "CorrespondantOrd", "CorrespondantCle")}
            if att and any(got[k] != v for k, v in att.items()):
                add("BLOQUANT", "C17", f"Compte correspondant {dev} absent ou différent", ref, "Règlement",
                    "Correspondant…", "/".join(got.values()) or "(vide)", "/".join(att.values()))
            if not att and any(got.values()):
                add("A_VERIFIER", "C18", f"Compte correspondant renseigné pour une opération en {dev}", ref, "Règlement",
                    "Correspondant…", "/".join(got.values()), "(vide)")
            inter = intermediaire(params, swift11(g.get("CODE BIC")), dev)
            if inter and _s(g.get("INTERMEDIAIRE FINAN")) != inter:
                add("A_VERIFIER", "C19", "Banque intermédiaire différente du référentiel", ref, "Règlement",
                    "INTERMEDIAIRE FINAN", _s(g.get("INTERMEDIAIRE FINAN")) or "(vide)", inter)
        # doublon de période pour un même client
        per = periode_canon(t.get("Reference denotage") or t.get("Objet du transfert") or d.get("Description") or g.get("Transfer Object"))
        cl = _s(t.get("Code client") or d.get("Identifient client")) or cl_reg
        if per and cl:
            clients_periodes.setdefault((cl, per[:7]), []).append((ref, per[7:] or None))
        if _s(d.get("Numéro domiciliation")) and _s(d.get("Date domiciliation")):
            dom_dates.setdefault(_s(d.get("Numéro domiciliation")), set()).add(_s(d.get("Date domiciliation")))
        if planning is not None and not planning.empty and per and cl:
            p = planning[(planning["SIEGE_RACINE"].astype(str) == cl) & (planning["PERIODE_TL"].astype(str) == per)]
            if p.empty:
                add("A_VERIFIER", "P01", f"Période {per} absente du Planning TL du client", ref)
            else:
                mt = _num(t.get("Montant") or d.get("Montant"))
                mx = _num(p["MONTANT_MAX_THEORIQUE"].iloc[0])
                if mt and mx and mt > mx + 1:
                    add("BLOQUANT", "P02", f"Montant {mt:,.2f} > part domiciliée de la période {mx:,.2f}", ref)
                ndom = _s(t.get("N° domiciliation") or d.get("Numéro domiciliation"))
                pdom = digits(p["NUMERO_DOMICILIATION"].iloc[0])
                if ndom and pdom and digits(ndom) != pdom:
                    add("BLOQUANT", "P03", "N° de domiciliation ≠ Planning", ref, val=ndom, att=p["NUMERO_DOMICILIATION"].iloc[0])
    if len(dvs) > 1:
        add("A_VERIFIER", "C20", f"Plusieurs dates valeur dans le lot : {', '.join(sorted(dvs))}")
    for (cl, mois), lst in clients_periodes.items():
        if len(lst) > 1:
            tr = [x[1] or "COMPLET" for x in lst]
            if len(tr) != len(set(tr)) or ("COMPLET" in tr and len(tr) > 1):
                add("BLOQUANT", "C21", f"Même client, même mois {mois} transféré plusieurs fois : {', '.join(x[0] for x in lst)}",
                    ", ".join(x[0] for x in lst))
    for dom, ds in dom_dates.items():
        if len(ds) > 1:
            add("A_VERIFIER", "C22", f"Plusieurs dates de domiciliation pour la DOM {dom} : {', '.join(sorted(ds))}", fichier="DOM")
    cols = ["NIVEAU", "CODE", "REF_TL", "FICHIER", "COLONNE", "VALEUR", "ATTENDU", "ANOMALIE"]
    out = pd.DataFrame(an, columns=cols)
    return out.sort_values(["NIVEAU", "CODE", "REF_TL"], key=lambda s: s.map({"BLOQUANT": 0, "A_VERIFIER": 1}) if s.name == "NIVEAU" else s,
                           na_position="last").reset_index(drop=True)


def carthago_dom_dates(path: Path | None) -> pd.DataFrame:
    """Dates de domiciliation de l'export CarthagoDom (n° DOM -> date), si la colonne existe."""
    if not path or not Path(path).exists():
        return pd.DataFrame(columns=["_DOM", "_DATE"])
    from . import carthago
    try:
        df = pd.read_excel(path, dtype=object)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["_DOM", "_DATE"])
    hdr = [str(c) for c in df.columns]
    det = carthago.detect(hdr)
    dcol = next((h for h in hdr if carthago.key(h) in ("DATE DOMICILIATION", "DATE DE DOMICILIATION", "DATE DOM",
                                                         "DATE CREATION", "DATE DE CREATION")), None)
    if not det.get("dom_ref") or not dcol:
        return pd.DataFrame(columns=["_DOM", "_DATE"])
    return pd.DataFrame({"_DOM": df[det["dom_ref"]].map(lambda v: (digits(v) + "DZD") if digits(v) else None),
                         "_DATE": df[dcol].map(parse_date)}).dropna()


# ----------------------------------------------------------------------------- fichier Trade pour l'agence
def trade_agence(lignes: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Pré-saisie pour l'agence (création des TL dans CarthagoTrade) : colonnes du fichier Trade, sans
    référence TL, statut, étape ni date valeur (attribués ensuite par CarthagoTrade / le BOCI)."""
    g = generer(lignes.assign(REF_TL=""), date.today(), params)["trade"]
    for c in ("Référence", "Statut", "Etape en cours", "Date valeur"):
        g[c] = ""
    return g
