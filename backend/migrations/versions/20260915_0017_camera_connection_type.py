"""persist camera connection type

Revision ID: 20260915_0017
Revises: 20260915_0016
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0017"
down_revision: str | None = "20260915_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cameras" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("cameras")}
    if "connection_type" not in columns:
        op.add_column(
            "cameras",
            sa.Column(
                "connection_type",
                sa.String(length=32),
                nullable=False,
                server_default="manual_rtsp",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cameras" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("cameras")}
    if "connection_type" in columns:
        with op.batch_alter_table("cameras") as batch_op:
            batch_op.drop_column("connection_type")
