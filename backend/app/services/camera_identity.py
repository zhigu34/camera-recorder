from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CameraFormFactor = Literal["unknown", "bullet", "dome", "turret", "ptz", "doorbell", "indoor", "panoramic"]
CameraIdentityConfidence = Literal["high", "medium"]


@dataclass(frozen=True)
class CameraFormFactorGuess:
    form_factor: CameraFormFactor
    confidence: CameraIdentityConfidence
    source: str
    rule: str


def _compact(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def _brand(manufacturer: str | None) -> str:
    raw = (manufacturer or "").strip().upper()
    if "海康" in raw:
        return "hikvision"
    if "大华" in raw:
        return "dahua"
    if "萤石" in raw:
        return "ezviz"

    value = _compact(raw)
    aliases = {
        "HIKVISION": "hikvision",
        "DAHUA": "dahua",
        "REOLINK": "reolink",
        "UBIQUITI": "unifi",
        "UNIFI": "unifi",
        "TPLINK": "tplink",
        "TAPO": "tplink",
        "EZVIZ": "ezviz",
    }
    for alias, normalized in aliases.items():
        if alias in value:
            return normalized
    return value.lower()


def infer_camera_form_factor(
    manufacturer: str | None,
    model: str | None,
) -> CameraFormFactorGuess | None:
    """Infer physical camera shape from conservative model-name rules.

    Rules intentionally favor precision over recall. Unknown or ambiguous models
    return None so callers can preserve a manually selected form factor instead
    of guessing incorrectly.
    """

    raw_model = (model or "").strip()
    if not raw_model:
        return None

    upper_model = raw_model.upper()
    compact_model = _compact(raw_model)
    brand = _brand(manufacturer)

    # Explicit product-family words are the safest cross-vendor signal.
    generic_words: tuple[tuple[str, CameraFormFactor], ...] = (
        ("DOORBELL", "doorbell"),
        ("PANORAMIC", "panoramic"),
        ("FISHEYE", "panoramic"),
        ("TURRET", "turret"),
        ("BULLET", "bullet"),
        ("DOME", "dome"),
        ("PTZ", "ptz"),
    )
    for word, form_factor in generic_words:
        if word in upper_model:
            return CameraFormFactorGuess(form_factor, "high", "model_keyword", word.lower())

    # EZVIZ consumer cameras use CS-* identifiers. Installations often store the
    # manufacturer as Hikvision (the parent/vendor ecosystem), so recognize these
    # product families from the model itself rather than requiring manufacturer=EZVIZ.
    if re.search(r"^CSC6(?:C|CN|WI|N|W|$)", compact_model) or compact_model.startswith("CSC60P"):
        return CameraFormFactorGuess("ptz", "high", "model_catalog", "ezviz_c6_ptz")
    if compact_model.startswith("CSC8C"):
        return CameraFormFactorGuess("ptz", "high", "model_catalog", "ezviz_c8c_ptz")
    if compact_model.startswith("CSE4P"):
        return CameraFormFactorGuess("panoramic", "high", "model_catalog", "ezviz_e4p_panoramic")

    # Recognizable catalog prefixes can identify the vendor even if manufacturer
    # was never filled in. This keeps automatic shape inference useful for legacy
    # rows imported before identity metadata existed.
    if compact_model.startswith("DS2"):
        brand = "hikvision"
    elif compact_model.startswith(("IPCHFW", "IPCHDBW", "IPCHDW")):
        brand = "dahua"
    elif compact_model.startswith("RLC") or compact_model.startswith(("VIDEODOORBELL", "TRACKMIX")):
        brand = "reolink"

    if brand == "hikvision":
        rules: tuple[tuple[str, CameraFormFactor], ...] = (
            (r"^DS2DE", "ptz"),
            (r"^DS2CD(?:2T|16|26)", "bullet"),
            (r"^DS2CD(?:13|23|33)", "turret"),
            (r"^DS2CD(?:11|21)", "dome"),
        )
        for pattern, form_factor in rules:
            if re.search(pattern, compact_model):
                return CameraFormFactorGuess(form_factor, "high", "model_catalog", pattern)

    if brand == "dahua":
        rules = (
            (r"^IPCHFW", "bullet"),
            (r"^IPCHDBW", "dome"),
            (r"^IPCHDW", "turret"),
            (r"^SD[0-9A-Z]", "ptz"),
        )
        for pattern, form_factor in rules:
            if re.search(pattern, compact_model):
                return CameraFormFactorGuess(form_factor, "high", "model_catalog", pattern)

    if brand == "reolink":
        # Reolink naming is less regular, so only keep product families whose
        # physical shape is stable across the family.
        if re.search(r"^RLC(?:510|511|810|811)", compact_model):
            return CameraFormFactorGuess("bullet", "high", "model_catalog", "reolink_rlc_bullet")
        if re.search(r"^RLC(?:820|822|830|833)", compact_model):
            return CameraFormFactorGuess("turret", "high", "model_catalog", "reolink_rlc_turret")
        if compact_model.startswith("VIDEODOORBELL"):
            return CameraFormFactorGuess("doorbell", "high", "model_catalog", "reolink_doorbell")
        if compact_model.startswith("TRACKMIX"):
            return CameraFormFactorGuess("ptz", "high", "model_catalog", "reolink_trackmix")
        if compact_model in {"E1", "E1PRO", "E1ZOOM"}:
            return CameraFormFactorGuess("indoor", "high", "model_catalog", "reolink_e1_indoor")

    if brand == "unifi":
        if "DOORBELL" in compact_model:
            return CameraFormFactorGuess("doorbell", "high", "model_catalog", "unifi_doorbell")
        if "TURRET" in compact_model:
            return CameraFormFactorGuess("turret", "high", "model_catalog", "unifi_turret")
        if "DOME" in compact_model:
            return CameraFormFactorGuess("dome", "high", "model_catalog", "unifi_dome")
        if "BULLET" in compact_model:
            return CameraFormFactorGuess("bullet", "high", "model_catalog", "unifi_bullet")
        if "PTZ" in compact_model:
            return CameraFormFactorGuess("ptz", "high", "model_catalog", "unifi_ptz")

    if brand == "tplink":
        if re.search(r"^C(?:200|210|220)$", compact_model):
            return CameraFormFactorGuess("indoor", "high", "model_catalog", "tapo_indoor")
        if re.search(r"^C(?:310|320|325)", compact_model):
            return CameraFormFactorGuess("bullet", "high", "model_catalog", "tapo_bullet")
        if re.search(r"^C(?:500|510|520)", compact_model):
            return CameraFormFactorGuess("ptz", "high", "model_catalog", "tapo_outdoor_ptz")

    return None
