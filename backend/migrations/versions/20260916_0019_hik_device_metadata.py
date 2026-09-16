"""persist HIK SDK device metadata

Revision ID: 20260916_0019
Revises: 20260915_0018
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0019"
down_revision: str | None = "20260915_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "cameras" not in tables or "hik_device_metadata" in tables:
        return
    op.create_table(
        "hik_device_metadata",
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("sdk_port", sa.Integer(), server_default="8000", nullable=False),
        sa.Column("channel", sa.Integer(), server_default="1", nullable=False),
        sa.Column("main_stream_type", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sub_stream_type", sa.Integer(), server_default="1", nullable=False),
        sa.Column("device_serial", sa.String(length=128), nullable=True),
        sa.Column("device_model", sa.String(length=128), nullable=True),
        sa.Column("device_name", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("camera_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hik_device_metadata" in set(inspector.get_table_names()):
        op.drop_table("hik_device_metadata")
