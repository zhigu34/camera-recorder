"""add camera identity metadata

Revision ID: 20260912_0009
Revises: 20260912_0008
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0009"
down_revision: str | None = "20260912_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch_op:
        batch_op.add_column(sa.Column("manufacturer", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column(
                "form_factor",
                sa.String(length=32),
                nullable=False,
                server_default="unknown",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("cameras") as batch_op:
        batch_op.drop_column("form_factor")
        batch_op.drop_column("model")
        batch_op.drop_column("manufacturer")
