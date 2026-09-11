"""add camera recording schedules

Revision ID: 20260911_0007
Revises: 20260911_0006
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0007"
down_revision: str | None = "20260911_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch_op:
        batch_op.add_column(
            sa.Column(
                "recording_schedule_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "recording_schedule",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("cameras") as batch_op:
        batch_op.drop_column("recording_schedule")
        batch_op.drop_column("recording_schedule_enabled")
