"""add HIK current connection config

Revision ID: 20260917_0024
Revises: 20260916_0023
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0024"
down_revision: str | None = "20260916_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hik_connection_configs",
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("sdk_port", sa.Integer(), server_default="8000", nullable=False),
        sa.Column("channel", sa.Integer(), server_default="1", nullable=False),
        sa.Column("main_stream_type", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sub_stream_type", sa.Integer(), server_default="1", nullable=False),
        sa.Column("device_serial", sa.String(length=128), nullable=True),
        sa.Column("device_model", sa.String(length=128), nullable=True),
        sa.Column("device_name", sa.String(length=128), nullable=True),
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
    op.drop_table("hik_connection_configs")
