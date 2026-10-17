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
    s = s.replace(" ", "").replace(" ", "")
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
    """Règle Partie 2 : regex 07310 + 6 chiffres (jamais une découpe par position)."""
    d = digits(v)
    m = SIEGE_RE.search(d)
    return m.group(0) if m else None


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


def render_page(pdf: Path, page_num: int, zoom: float = 1.4) -> bytes | None:
    """page_num commence à 1. Retourne un PNG."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # type: ignore
    try:
        with fitz.open(pdf) as d:
            i = max(0, min(int(page_num) - 1, len(d) - 1))
            return d[i].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
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
