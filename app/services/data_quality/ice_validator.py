"""
ICE Validation Service — Moroccan business identifier validation.

ICE format: 15 digits
  - 3 digits (RC reference)
  - 4 digits (CIN or equivalent)
  - 6 digits (sequence)
  - 2 digits (check key: modulo-97)

Key calculation: key = 97 - (body % 97), where body = first 13 digits.
"""
import re
from dataclasses import dataclass, field


@dataclass
class ICEResult:
    valid: bool
    ice: str
    error: str = ""
    rc_part: str = ""
    cin_part: str = ""
    sequence_part: str = ""
    key_part: str = ""
    key_valid: bool = False


def validate_ice(ice: str) -> ICEResult:
    """Validate a single ICE number with full breakdown."""
    if not ice or not ice.strip():
        return ICEResult(valid=False, ice="", error="ICE obligatoire")

    ice_clean = ice.strip().replace(" ", "").replace("-", "")

    if not ice_clean.isdigit():
        return ICEResult(valid=False, ice=ice_clean, error="ICE doit contenir uniquement des chiffres")

    if len(ice_clean) != 15:
        return ICEResult(valid=False, ice=ice_clean, error=f"ICE doit contenir 15 chiffres (reçu: {len(ice_clean)})")

    rc_part = ice_clean[:3]
    cin_part = ice_clean[3:7]
    sequence_part = ice_clean[7:13]
    key_part = ice_clean[13:15]

    try:
        body = int(ice_clean[:13])
        key = int(ice_clean[13:])
        expected_key = 97 - (body % 97)
        key_valid = key == expected_key
        if not key_valid:
            return ICEResult(
                valid=False, ice=ice_clean,
                error=f"ICE clé invalide (reçu: {key}, attendu: {expected_key})",
                rc_part=rc_part, cin_part=cin_part, sequence_part=sequence_part, key_part=key_part,
                key_valid=False,
            )
    except ValueError:
        return ICEResult(valid=False, ice=ice_clean, error="ICE format invalide")

    return ICEResult(
        valid=True, ice=ice_clean,
        rc_part=rc_part, cin_part=cin_part, sequence_part=sequence_part, key_part=key_part,
        key_valid=True,
    )


def validate_ice_batch(entries: list[dict]) -> list[dict]:
    """
    Validate a batch of ICE entries.
    Each entry: {"id": "...", "ice": "...", "name": "..."}
    Returns list with validation results appended.
    """
    results = []
    seen = {}
    for entry in entries:
        ice = entry.get("ice", "")
        result = validate_ice(ice)
        duplicate = ice in seen if result.valid else False
        results.append({
            **entry,
            "valid": result.valid,
            "error": result.error,
            "duplicate": duplicate,
            "rc_part": result.rc_part,
            "cin_part": result.cin_part,
        })
        if result.valid:
            seen[ice] = entry.get("id", "")
    return results


def generate_ice(body_13: str) -> str:
    """Generate a valid ICE from the first 13 digits."""
    body_13 = body_13.strip().replace(" ", "")[:13].ljust(13, "0")
    body_int = int(body_13)
    key = 97 - (body_int % 97)
    return f"{body_13}{key:02d}"
