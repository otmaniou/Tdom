"""Autorisations de transfert du portail « Personnel étranger : Transfert des salaires des expatriés ».

La page enregistrée (HTML) contient l'en-tête de la demande (NIF, RC, raison sociale, total de la demande,
nombre d'articles, code banque / agence) et un tableau d'articles :
    N° | Désignation « NOM PRÉNOM (AOUT) » | Stock | En cours | Qté « 1.0000 » | Unité « mois » | Prix unitaire | Total
Montant autorisé = Total de l'article (Qté × prix unitaire). Le mois vient de la désignation ; l'année n'y figure
pas : elle vient du nom du fichier / dossier (…/2026-08/…) ou est choisie au dépôt.
Contrôles : NIF de la demande = NIF de l'employeur, somme des articles = total de la demande, nombre d'articles.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

import pandas as pd

from .common import digits, parse_amount
from .periode import MOIS, _up

MOIS_RE = "|".join(sorted(MOIS, key=len, reverse=True))
DESIGN_RE = re.compile(rf"^(.*?)\s*\(\s*({MOIS_RE})\s*(\d{{2,4}})?\s*\)\s*$")


class _Doc(HTMLParser):
    """Texte de la page (lignes) + tableaux (cellules), sans dépendance externe."""
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "section", "td", "th"}

    def __init__(self):
        super().__init__()
        self.lines, self.cur = [], []
        self.tables, self.row, self.cell = [], None, None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        if tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.tables:
            if any(self.row):
                self.tables[-1].append(self.row)
            self.row = None
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, d):
        if self.skip:
            return
        self.cur.append(d)
        if self.cell is not None:
            self.cell.append(d)

    def _flush(self):
        t = " ".join(" ".join(self.cur).split())
        if t:
            self.lines.append(t)
        self.cur = []


def _after(lines: list[str], label: str) -> str | None:
    lab = _up(label)
    for i, ln in enumerate(lines):
        u = _up(ln)
        if u == lab or u.startswith(lab + " :") or u.startswith(lab + ":"):
            rest = ln.split(":", 1)[1].strip() if ":" in ln and u != lab else ""
            if rest:
                return rest
            return lines[i + 1] if i + 1 < len(lines) else None
    return None


def annee_depuis_nom(name: str) -> int | None:
    m = re.search(r"(20\d{2})[-_ ./]?(0[1-9]|1[0-2])?", str(name))
    return int(m.group(1)) if m else None


def lire(html: str | bytes, annee: int | None = None, nom_fichier: str = "") -> dict:
    """-> {entete: {...}, lignes: DataFrame(NOM_PRENOM, MOIS, QTE, PRIX_UNITAIRE, MONTANT_AUTORISE, N), controles: [...]}"""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    d = _Doc()
    d.feed(html)
    d._flush()
    lines = d.lines
    ent = {"NIF": digits(_after(lines, "NIF")), "RC": _after(lines, "RC"),
           "RAISON_SOCIALE": _after(lines, "Raison sociale"),
           "TOTAL_DEMANDE": parse_amount(re.sub(r"[^\d,.\s]", "", _after(lines, "Total de la demande") or "")),
           "NB_ARTICLES": None, "CODE_BANQUE": None, "CODE_AGENCE": None}
    for ln in lines:
        m = re.search(r"Articles?\s*\((\d+)\)", ln, re.I)
        if m and ent["NB_ARTICLES"] is None:
            ent["NB_ARTICLES"] = int(m.group(1))
        m = re.search(r"Code banque\s*:\s*(\d+).*?Code agence\s*:\s*(\d+)", ln, re.I)
        if m:
            ent["CODE_BANQUE"], ent["CODE_AGENCE"] = m.group(1), m.group(2)
    annee = annee or annee_depuis_nom(nom_fichier)
    rows = []
    # 1) tableau HTML : colonnes repérées par leur en-tête
    for tab in d.tables:
        head = [_up(x) for x in tab[0]] if tab else []
        if not any("DESIGNATION" in h for h in head):
            continue
        ix = {k: next((i for i, h in enumerate(head) if h.startswith(k)), None)
              for k in ("N", "DESIGNATION", "QTE", "UNITE", "PRIX UNITAIRE", "TOTAL")}
        for r in tab[1:]:
            def g(k):
                i = ix.get(k)
                return r[i] if i is not None and i < len(r) else None
            rows.append({"N": g("N"), "DESIGNATION": g("DESIGNATION"), "QTE": g("QTE"), "UNITE": g("UNITE"),
                         "PRIX": g("PRIX UNITAIRE"), "TOTAL": g("TOTAL")})
    # 2) sinon, lignes de texte : « 835 ERHAN ALI (AOUT) — — 1.0000 mois 410 542,13 DZD 410 542,13 DZD Domicilier »
    if not rows:
        txt = "\n".join(lines)
        pat = re.compile(rf"(?m)^\s*(\d{{1,5}})\s+(.+?\(\s*(?:{MOIS_RE})[^)]*\))\s*(?:[—–-]\s*)*\s*([\d.,]+)\s*mois\s*"
                         r"([\d\s .,]+?)\s*DZD\s+([\d\s .,]+?)\s*DZD", re.I)
        flat = re.sub(r"\n(?=[—–-]|\d+[.,]\d{4}\s*mois|[\d\s .,]+DZD|Domicilier)", " ", txt)
        for m in pat.finditer(flat):
            rows.append({"N": m.group(1), "DESIGNATION": m.group(2), "QTE": m.group(3), "UNITE": "mois",
                         "PRIX": m.group(4), "TOTAL": m.group(5)})
    out, ctl = [], []
    for r in rows:
        des = " ".join(str(r["DESIGNATION"] or "").split())
        m = DESIGN_RE.match(_up(des))
        if not m:
            ctl.append(f"Article {r['N']} : désignation sans mois « {des} »")
            continue
        mois = MOIS[m.group(2)]
        an = int(m.group(3)) if m.group(3) else annee
        if an and an < 100:
            an += 2000
        qte = parse_amount(r["QTE"]) or 1.0
        total = parse_amount(re.sub(r"[^\d,.\s ]", "", str(r["TOTAL"] or "")))
        prix = parse_amount(re.sub(r"[^\d,.\s ]", "", str(r["PRIX"] or "")))
        out.append({"N": int(digits(r["N"])) if digits(r["N"]) else None, "NOM_PRENOM": m.group(1).strip(),
                    "MOIS": f"{an:04d}-{mois:02d}" if an else None, "QTE_MOIS": qte, "PRIX_UNITAIRE": prix,
                    "MONTANT_AUTORISE": total if total is not None else (prix or 0) * qte, "DESIGNATION": des})
    df = pd.DataFrame(out, columns=["N", "NOM_PRENOM", "MOIS", "QTE_MOIS", "PRIX_UNITAIRE", "MONTANT_AUTORISE", "DESIGNATION"])
    if df.empty:
        ctl.append("Aucun article lu : la page ne contient pas le tableau des articles")
    else:
        if df["MOIS"].isna().any():
            ctl.append("Année absente de la désignation et du nom de fichier : à préciser au dépôt")
        if ent["NB_ARTICLES"] is not None and ent["NB_ARTICLES"] != len(df):
            ctl.append(f"{len(df)} article(s) lu(s) pour {ent['NB_ARTICLES']} annoncé(s)")
        if ent["TOTAL_DEMANDE"] is not None and abs(df["MONTANT_AUTORISE"].sum() - ent["TOTAL_DEMANDE"]) > 1:
            ctl.append(f"Somme des articles {df['MONTANT_AUTORISE'].sum():,.2f} ≠ total de la demande "
                       f"{ent['TOTAL_DEMANDE']:,.2f}")
        bad = df[(df["QTE_MOIS"] * df["PRIX_UNITAIRE"].fillna(0) - df["MONTANT_AUTORISE"]).abs() > 1]
        for r in bad.itertuples():
            ctl.append(f"Article {r.N} : quantité × prix ≠ total")
        dup = df[df.duplicated(["NOM_PRENOM", "MOIS"], keep=False)]
        if not dup.empty:
            ctl.append(f"{dup['NOM_PRENOM'].nunique()} salarié(s) en double dans la demande")
    return {"entete": ent, "lignes": df, "controles": ctl}


def est_portail(html: str | bytes) -> bool:
    s = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    return "Transfert des salaires des expatri" in s or ("Désignation" in s and "Domicilier" in s)


def vers_referentiel(res: dict, nif_employeur: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Lignes au format du référentiel des autorisations TL-One + contrôles (dont le NIF de l'employeur)."""
    ctl = list(res["controles"])
    ent = res["entete"]
    if nif_employeur and ent.get("NIF") and digits(nif_employeur) != ent["NIF"]:
        ctl.insert(0, f"NIF de la demande {ent['NIF']} ≠ NIF de l'employeur {digits(nif_employeur)}")
    df = res["lignes"]
    out = pd.DataFrame({"NOM_PRENOM": df["NOM_PRENOM"], "COMPTE": None, "MOIS": df["MOIS"],
                        "MONTANT_AUTORISE": df["MONTANT_AUTORISE"], "DATE_VALIDATION": None, "DATE_LIMITE": None,
                        "AUTORISATION_REFERENCE": [f"PORTAIL {ent.get('NIF') or ''} art. {n}" for n in df["N"]]})
    return out, ctl
