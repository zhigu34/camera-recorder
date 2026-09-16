"""add ONVIF current connection config

Revision ID: 20260916_0023
Revises: 20260916_0022
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0023"
down_revision: str | None = "20260916_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "onvif_connection_configs",
        sa.Column("connection_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["camera_connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("connection_id"),
    )


def downgrade() -> None:
    op.drop_table("onvif_connection_configs")
