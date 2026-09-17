"""allow unverified ONVIF connections without discovery cache

Revision ID: 20260917_0025
Revises: 20260917_0024
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0025"
down_revision: str | None = "20260917_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("onvif_connection_configs") as batch_op:
        batch_op.alter_column(
            "recording_profile_token",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        batch_op.alter_column(
            "recording_uri",
            existing_type=sa.String(length=2048),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("onvif_connection_configs") as batch_op:
        batch_op.alter_column(
            "recording_uri",
            existing_type=sa.String(length=2048),
            nullable=False,
        )
        batch_op.alter_column(
            "recording_profile_token",
            existing_type=sa.String(length=255),
            nullable=False,
        )
