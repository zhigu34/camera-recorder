"""persist ONVIF device identity details

Revision ID: 20260918_0026
Revises: 20260917_0025
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_0026"
down_revision: str | None = "20260917_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "onvif_connection_configs",
        sa.Column("firmware_version", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "onvif_connection_configs",
        sa.Column("serial_number", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "onvif_connection_configs",
        sa.Column("hardware_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("onvif_connection_configs") as batch:
        batch.drop_column("hardware_id")
        batch.drop_column("serial_number")
        batch.drop_column("firmware_version")
