"""Utilitaires partagés : parsing, audit, identité utilisateur, aperçu PDF."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd


# ----------------------------------------------------------------- valeurs
def is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    try:
        if v is pd.NaT or (not isinstance(v, (str, bytes)) and pd.isna(v)):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip().lower() in ("", "nan", "none", "null", "nat")


def clean(v):
    return None if is_blank(v) else v


def parse_date(v):
    """Identique au notebook Planning_TL_V15A (jour en premier)."""
    if is_blank(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):        # cases de l'OV lues sans séparateur : 24052026 (JJMMAAAA) ou 20260524
        for fmt in ("%Y%m%d", "%d%m%Y"):
            try:
                d = datetime.strptime(s, fmt).date()
                if 1990 <= d.year <= 2100:
                    return d
            except ValueError:
                pass
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    x = pd.to_datetime(v, dayfirst=True, errors="coerce")
    return None if pd.isna(x) else x.date()


def parse_amount(v):
    """Identique au notebook Planning_TL_V15A (gère 1 261 600,00 / 454:835:67)."""
    if is_blank(v):
        return None
    if isinstance(v, (int, float, np.number)) and not isinstance(v, bool):
        return float(v)
    s = str(v).upper().strip()
    s = s.replace(" ", "").replace("\u00a0", "")
    s = s.replace("DZD", "").replace("DA", "")
    s = s.replace(":", ".")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) <= 2 else "".join(parts)
    elif s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) <= 2 else "".join(parts)
    s = re.sub(r"[^0-9.+-]", "", s)
    try:
        return float(s)
    except Exception:
        return None


def digits(v) -> str:
    return "" if is_blank(v) else re.sub(r"\D", "", str(v))


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_name(v) -> str:
    if is_blank(v):
        return ""
    s = strip_accents(str(v)).upper()
    s = re.sub(r"[^A-Z ]", " ", s)
    return " ".join(sorted(t for t in s.split() if len(t) > 1))


def name_similarity(a, b) -> float | None:
    """Similarité insensible à l'ordre nom/prénom (0-1). None si une valeur manque."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return None
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / max(1, len(ta | tb))
    return round(max(jacc, SequenceMatcher(None, na, nb).ratio()), 3)


SIEGE_RE = re.compile(r"07310\d{6}")


def siege_racine(v) -> str | None:
    """Identifiant client (ID tiers) = siège (5) + racine (6), toutes agences (07310, 07410…) :
    - RIB de 20 chiffres : DROITE(GAUCHE(compte;15);11) ;
    - ID tiers « 07410 109109 », compte BOCI 16 chiffres « 0731010920500191 », nom de fichier
      « 07310-990104-202609P1 » : les 11 premiers chiffres (commençant par 0)."""
    d = digits(v)
    if not d:
        return None
    if len(d) == 20 or (len(d) > 20 and d.startswith("0270")):   # RIB BNP (02700…), seul ou suivi d'une période
        return d[4:15]
    if len(d) >= 11 and d[0] == "0":
        return d[:11]
    m = SIEGE_RE.search(d)
    return m.group(0) if m else None


def id_tiers(v) -> str | None:
    """ID tiers normalisé (11 chiffres) depuis « 07410 109109 », « 07410-109109 » ou un RIB."""
    return siege_racine(v)


def id_tiers_affiche(v) -> str | None:
    c = id_tiers(v)
    return f"{c[:5]} {c[5:]}" if c else None


def dom_ref_compact(v) -> str | None:
    """Règle Partie 2 : tous les chiffres de la référence + suffixe DZD."""
    d = digits(v)
    return f"{d}DZD" if d else None


# ----------------------------------------------------------------- identité / audit
def current_user() -> str:
    try:
        import streamlit as st
        h = st.context.headers
        for k in ("domino-username", "Domino-Username", "x-domino-username"):
            if h.get(k):
                return h.get(k)
    except Exception:
        pass
    return os.environ.get("DOMINO_STARTING_USERNAME") or os.environ.get("USER") or "inconnu"


def audit(path: Path, action: str, user: str, **details) -> None:
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "user": user, "action": action, **details}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    bdir = path.parent / "_backups"
    bdir.mkdir(exist_ok=True)
    dst = bdir / f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"
    shutil.copy2(path, dst)
    return dst


# ----------------------------------------------------------------- PDF
def find_pdf(folder: Path, name: str | None) -> Path | None:
    if not name or not folder.exists():
        return None
    p = folder / str(name)
    if p.exists():
        return p
    stem = Path(str(name)).stem.lower()
    for q in folder.iterdir():
        if q.is_file() and q.suffix.lower() == ".pdf" and q.stem.lower() == stem:
            return q
    return None


def render_page(pdf: Path, page_num: int, zoom: float = 1.4, rotate: int = 0) -> bytes | None:
    """page_num commence à 1. Retourne un PNG. `rotate` : rotation horaire supplémentaire (redressement)."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # type: ignore
    try:
        with fitz.open(pdf) as d:
            i = max(0, min(int(page_num) - 1, len(d) - 1))
            pg = d[i]
            if rotate:
                pg.set_rotation((pg.rotation + int(rotate)) % 360)
            return pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
    except Exception:
        return None


def page_count(pdf: Path) -> int:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # type: ignore
    try:
        with fitz.open(pdf) as d:
            return len(d)
    except Exception:
        return 0


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name[:31], index=False)
    return buf.getvalue()


# ------------------------------------------------------------------ cache disque des gros fichiers lus
CACHE_VERSION = "2"   # à incrémenter quand la lecture d une base change (relecture forcée)


def cached_read(path, tag: str, fn):
    """Résultat de fn(path) mis en cache sur disque (dossier .cache_tlone à côté du fichier), invalidé dès que le
    fichier change (taille, date). Une base RH ou une ATF de 10 000 à 20 000 lignes n'est lue qu'une fois :
    les pages, l'Accueil et le worker relisent ensuite le cache en une fraction de seconde."""
    import pickle
    p = Path(path)
    try:
        st_ = p.stat()
    except OSError:
        return fn(p)
    key = f"{CACHE_VERSION}|{tag}|{st_.st_size}|{st_.st_mtime_ns}"
    cdir = p.parent / ".cache_tlone"
    cfile = cdir / f"{p.name}.{tag}.pkl"
    try:
        if cfile.exists():
            with cfile.open("rb") as f:
                k, val = pickle.load(f)
            if k == key:
                return val
    except Exception:  # noqa: BLE001  cache illisible : relecture
        pass
    val = fn(p)
    try:
        cdir.mkdir(exist_ok=True)
        tmp = cfile.with_suffix(f".{os.getpid()}.tmp")
        with tmp.open("wb") as f:
            pickle.dump((key, val), f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cfile)
    except Exception:  # noqa: BLE001  dossier en lecture seule : pas de cache
        pass
    return val


# ----------------------------------------------------------------- comptes : lecture de l'OV et affichage
def rib_cle_ok(d: str) -> bool:
    """Clé Modulo 97 d'un RIB de 20 chiffres (même règle que la Partie 2 : chiffres 4 à 20)."""
    return len(d) == 20 and d.isdigit() and int(d[3:20]) % 97 == 0


def compte_ov(v, date_lue=None) -> tuple[str | None, date | None]:
    """Ligne « Date | Siège | Racine | Ordinal | Clé | devise » de l'OV lue d'un bloc (le modèle y colle parfois la
    date) -> (RIB de 20 chiffres, date). Structure : date jjmmaaaa (jj|mm|aaaa, jjmm aaaa), code banque 027 parfois
    absent, siège 5, racine 6, ordinal 3, clé 2, devise DZD. Le RIB est reconstitué tel que sur l'OV : 0270 + siège +
    racine + ordinal + clé ; on garde la lecture dont la clé Modulo 97 est juste."""
    if is_blank(v):
        return None, None
    d = digits(re.sub(r"(?i)DZD|DA\b", "", str(v)))
    dte = None
    if len(d) >= 24:                                   # date collée devant le compte
        try:
            x = datetime.strptime(d[:8], "%d%m%Y").date()
            if 2000 <= x.year <= 2100:
                dte, d = x, d[8:]
        except ValueError:
            pass
    cands = []
    if len(d) == 20:
        cands.append(d)
    if len(d) == 19 and d.startswith("027"):
        cands.append("0270" + d[3:])
    if len(d) == 16:
        cands.append("0270" + d)
    if len(d) == 17 and d.startswith("0"):
        cands.append("027" + d)
    ok = next((c for c in cands if rib_cle_ok(c)), None)
    return (ok or (cands[0] if cands else (d or None))), dte


def fmt_compte(v) -> str | None:
    """027 007310 108448 001 30 (RIB 20 chiffres) ; 07310 108448 (identifiant client) ; sinon tel quel."""
    if is_blank(v):
        return None
    d = digits(v)
    if len(d) == 20 and re.fullmatch(r"[\d\s.|-]+", str(v).strip()):
        return f"{d[:3]} {d[3:9]} {d[9:15]} {d[15:18]} {d[18:]}"
    if len(d) == 11 and re.fullmatch(r"[\d\s.|-]+", str(v).strip()):
        return f"{d[:5]} {d[5:]}"
    return str(v).strip()


def fmt_iban(v) -> str | None:
    """IBAN par groupes de 4 (TR27 0006 7010 0000 0043 5365 10). Compte sans IBAN (ex. Inde, numéro seul) :
    groupes de 4 aussi, pour la lecture seulement. Le contrôle compare toujours la valeur sans espaces."""
    if is_blank(v):
        return None
    s = re.sub(r"[^A-Z0-9]", "", str(v).upper())
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4)) if s else None
