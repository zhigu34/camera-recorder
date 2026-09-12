"""backfill inferred camera form factors

Revision ID: 20260912_0012
Revises: 20260912_0011
Create Date: 2026-09-12
"""

from collections.abc import Sequence
import re

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0012"
down_revision: str | None = "20260912_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _compact(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def _brand(manufacturer: str | None, compact_model: str) -> str:
    raw = (manufacturer or "").strip().upper()
    if "海康" in raw or "HIKVISION" in _compact(raw):
        return "hikvision"
    if "大华" in raw or "DAHUA" in _compact(raw):
        return "dahua"
    value = _compact(raw)
    if "REOLINK" in value:
        return "reolink"
    if "UBIQUITI" in value or "UNIFI" in value:
        return "unifi"
    if "TPLINK" in value or "TAPO" in value:
        return "tplink"

    if compact_model.startswith(("DS2CD", "DS2DE")):
        return "hikvision"
    if compact_model.startswith(("IPCHFW", "IPCHDBW", "IPCHDW")) or re.match(r"^SD[0-9A-Z]", compact_model):
        return "dahua"
    if compact_model.startswith(("RLC", "VIDEODOORBELL", "TRACKMIX")) or compact_model in {"E1", "E1PRO", "E1ZOOM"}:
        return "reolink"
    if compact_model.startswith("UVC"):
        return "unifi"
    return ""


def _infer(manufacturer: str | None, model: str | None) -> str | None:
    raw_model = (model or "").strip()
    if not raw_model:
        return None

    upper_model = raw_model.upper()
    compact_model = _compact(raw_model)
    for word, form_factor in (
        ("DOORBELL", "doorbell"),
        ("TURRET", "turret"),
        ("BULLET", "bullet"),
        ("DOME", "dome"),
        ("PTZ", "ptz"),
    ):
        if word in upper_model:
            return form_factor

    brand = _brand(manufacturer, compact_model)
    if brand == "hikvision":
        for pattern, form_factor in (
            (r"^DS2DE", "ptz"),
            (r"^DS2CD(?:2T|16|26)", "bullet"),
            (r"^DS2CD(?:13|23|33)", "turret"),
            (r"^DS2CD(?:11|21)", "dome"),
        ):
            if re.search(pattern, compact_model):
                return form_factor

    if brand == "dahua":
        for pattern, form_factor in (
            (r"^IPCHFW", "bullet"),
            (r"^IPCHDBW", "dome"),
            (r"^IPCHDW", "turret"),
            (r"^SD[0-9A-Z]", "ptz"),
        ):
            if re.search(pattern, compact_model):
                return form_factor

    if brand == "reolink":
        if re.search(r"^RLC(?:510|511|810|811)", compact_model):
            return "bullet"
        if re.search(r"^RLC(?:820|822|830|833)", compact_model):
            return "turret"
        if compact_model.startswith("VIDEODOORBELL"):
            return "doorbell"
        if compact_model.startswith("TRACKMIX"):
            return "ptz"
        if compact_model in {"E1", "E1PRO", "E1ZOOM"}:
            return "indoor"

    if brand == "unifi":
        for word, form_factor in (
            ("DOORBELL", "doorbell"),
            ("TURRET", "turret"),
            ("DOME", "dome"),
            ("BULLET", "bullet"),
            ("PTZ", "ptz"),
        ):
            if word in compact_model:
                return form_factor

    if brand == "tplink":
        if re.search(r"^C(?:200|210|220)$", compact_model):
            return "indoor"
        if re.search(r"^C(?:310|320|325)", compact_model):
            return "bullet"
        if re.search(r"^C(?:500|510|520)", compact_model):
            return "ptz"

    return None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, manufacturer, model FROM cameras "
            "WHERE form_factor = 'unknown' OR form_factor IS NULL"
        )
    ).mappings()
    for row in rows:
        form_factor = _infer(row["manufacturer"], row["model"])
        if not form_factor:
            continue
        bind.execute(
            sa.text(
                "UPDATE cameras SET form_factor = :form_factor "
                "WHERE id = :camera_id AND (form_factor = 'unknown' OR form_factor IS NULL)"
            ),
            {"camera_id": row["id"], "form_factor": form_factor},
        )


def downgrade() -> None:
    # Data backfills are intentionally not reverted because a migrated value is
    # indistinguishable from a user-selected form factor after the upgrade.
    pass
