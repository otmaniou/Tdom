"""Mapping strict et unique des exports CarthagoDom pour TL-One.

- Un seul fichier de configuration : config/carthagodom_columns.json.
- Les en-têtes sont comparés à l'identique (casse, accents, espaces compris).
- Aucune détection de variantes ni rapprochement flou.
- Les champs dont le nom réel est inconnu restent null ; le traitement échoue
  explicitement tant qu'ils ne sont pas renseignés pour la certification.
- Ce module ne prétend PAS que la source bancaire possède toutes les colonnes.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "carthagodom_columns.json"
CANONICAL_FIELDS = (
    "client_code", "nom_complet", "reference_dom", "compte_local",
    "montant_total", "statut_domiciliation"
)

class CarthagoMappingError(ValueError):
    """Erreur explicite de configuration ou d'en-têtes ; aucun fallback."""


def load_mapping(path: str | Path = DEFAULT_CONFIG) -> dict:
    p = Path(path)
    try:
        mapping = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CarthagoMappingError(f"CONFIG_ILLISIBLE: {p}: {exc}") from exc
    if not isinstance(mapping, dict) or not isinstance(mapping.get("colonnes"), dict):
        raise CarthagoMappingError("CONFIG_INVALIDE: objet 'colonnes' absent")
    cols = mapping["colonnes"]
    if set(cols) != set(CANONICAL_FIELDS):
        raise CarthagoMappingError(
            "CONFIG_INVALIDE: les clés techniques doivent être exactement "
            + ", ".join(CANONICAL_FIELDS)
        )
    for key, label in cols.items():
        if label is not None and (not isinstance(label, str) or not label.strip() or label != label.strip()):
            raise CarthagoMappingError(
                f"CONFIG_INVALIDE: '{key}' doit être un libellé non vide, "
                "sans espaces parasites en début ou fin, ou null."
            )
    labels = [x for x in cols.values() if x is not None]
    if len(labels) != len(set(labels)):
        raise CarthagoMappingError("CONFIG_INVALIDE: même libellé source affecté à plusieurs champs")
    required = mapping.get("champs_obligatoires_pour_certification")
    if not isinstance(required, list) or any(f not in cols for f in required):
        raise CarthagoMappingError("CONFIG_INVALIDE: liste champs_obligatoires_pour_certification")
    statuses = mapping.get("valeurs_statut_valide")
    if not isinstance(statuses, list) or any(not isinstance(v, str) or not v for v in statuses):
        raise CarthagoMappingError("CONFIG_INVALIDE: valeurs_statut_valide doit être une liste de chaînes")
    return mapping


def mapping_fingerprint(path: str | Path = DEFAULT_CONFIG) -> str:
    """Empreinte de la configuration. Toute modification invalide un certificat antérieur."""
    mapping = load_mapping(path)
    payload = json.dumps(mapping, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_configuration_ready(mapping: dict) -> None:
    cols = mapping["colonnes"]
    unknown = [key for key in mapping["champs_obligatoires_pour_certification"] if cols[key] is None]
    if unknown:
        raise CarthagoMappingError(
            "LIBELLES_NON_CONFIGURES: compléter uniquement config/carthagodom_columns.json : "
            + ", ".join(unknown)
            + ". Aucun alias n'est recherché."
        )
    if not mapping["valeurs_statut_valide"]:
        raise CarthagoMappingError(
            "STATUT_VALIDE_NON_CONFIGURE: renseigner les valeurs exactes autorisant "
            "validation_agence_confirmee dans config/carthagodom_columns.json"
        )


def check_headers(headers: Sequence[str], mapping: dict, *, require_ready: bool = True) -> dict:
    """Les noms ne sont jamais modifiés ; aucun strip, casefold, alias ou fuzzy matching."""
    if any(not isinstance(h, str) for h in headers):
        raise CarthagoMappingError("EN_TETE_INVALIDE: intitulés non textuels")
    duplicates = sorted(x for x, n in Counter(headers).items() if n > 1)
    if duplicates:
        raise CarthagoMappingError(f"COLONNES_DUPLIQUEES: {duplicates}")
    if require_ready:
        check_configuration_ready(mapping)
    expected = mapping["colonnes"]
    missing = {key: label for key, label in expected.items() if label is not None and label not in headers}
    if missing:
        details = "; ".join(f"{k} attendu exactement '{v}'" for k,v in missing.items())
        raise CarthagoMappingError("COLONNES_ABSENTES: " + details)
    return {
        "configured": {k:v for k,v in expected.items() if v is not None},
        "unconfigured": [k for k,v in expected.items() if v is None],
        "ignored_source_columns": [h for h in headers if h not in expected.values()],
        "mode": "STRICT_EXACT_ONLY"
    }


def map_bank_row(
    row: Mapping[str, Any],
    mapping: dict,
    *,
    employeur_id: str,
    snapshot_sha256: str,
    record_id: str,
    match_cardinality: int,
    mapping_sha256: str,
) -> dict:
    """Mappe UNE ligne déjà rattachée sans inventer les colonnes manquantes.

    La sélection de la bonne ligne reste une responsabilité du module de
    rapprochement bancaire ; elle ne se déduit pas de ce mapping.
    """
    check_headers(list(row.keys()), mapping)
    result: dict[str, Any] = {}
    for technical, label in mapping["colonnes"].items():
        value = row.get(label) if label is not None else None
        if isinstance(value, str) and not value.strip():
            value = None
        result[technical] = value
    missing_values = [k for k in mapping["champs_obligatoires_pour_certification"] if result[k] is None]
    if missing_values:
        raise CarthagoMappingError("VALEURS_BANCAIRES_VIDES: " + ", ".join(missing_values))
    # Sécurité : NE PAS interpréter un statut absent ou simplement non vide comme validation.
    status = result["statut_domiciliation"]
    result["validation_agence_confirmee"] = (
        isinstance(status, str) and status in mapping["valeurs_statut_valide"]
    )
    result.update({
        "employeur_id": employeur_id,
        "snapshot_sha256": snapshot_sha256,
        "record_id": record_id,
        "match_cardinality": match_cardinality,
        "column_mapping_sha256": mapping_sha256,
    })
    return result


def explain_configuration(path: str | Path = DEFAULT_CONFIG) -> dict:
    cfg = load_mapping(path)
    return {
        "config_file": str(Path(path)),
        "configured": {k:v for k,v in cfg["colonnes"].items() if v is not None},
        "to_confirm": [k for k,v in cfg["colonnes"].items() if v is None],
        "statuses_to_confirm": cfg["valeurs_statut_valide"],
        "mapping_sha256": mapping_fingerprint(path),
    }

if __name__ == "__main__":
    print(json.dumps(explain_configuration(), ensure_ascii=False, indent=2))
