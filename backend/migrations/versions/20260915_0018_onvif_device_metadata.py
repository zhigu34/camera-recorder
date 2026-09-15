"""persist ONVIF device metadata

Revision ID: 20260915_0018
Revises: 20260915_0017
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0018"
down_revision: str | None = "20260915_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "cameras" not in tables or "onvif_device_metadata" in tables:
        return
    op.create_table(
        "onvif_device_metadata",
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("device_service_url", sa.String(length=1024), nullable=False),
        sa.Column("device_uuid", sa.String(length=255), nullable=True),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("profiles_json", sa.JSON(), nullable=False),
        sa.Column("recording_profile_token", sa.String(length=255), nullable=False),
        sa.Column("preview_profile_token", sa.String(length=255), nullable=True),
        sa.Column("detection_profile_token", sa.String(length=255), nullable=True),
        sa.Column("recording_uri", sa.String(length=2048), nullable=False),
        sa.Column("preview_uri", sa.String(length=2048), nullable=True),
        sa.Column("detection_uri", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("camera_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "onvif_device_metadata" in set(inspector.get_table_names()):
        op.drop_table("onvif_device_metadata")
