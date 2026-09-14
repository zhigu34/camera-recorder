"""add motion event minimum interval

Revision ID: 20260914_0015
Revises: 20260914_0014
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0015"
down_revision: str | None = "20260914_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "motion_detection_settings" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("motion_detection_settings")}
    if "event_min_interval_ms" not in columns:
        op.add_column(
            "motion_detection_settings",
            sa.Column(
                "event_min_interval_ms",
                sa.Integer(),
                nullable=False,
                server_default="60000",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "motion_detection_settings" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("motion_detection_settings")}
    if "event_min_interval_ms" in columns:
        with op.batch_alter_table("motion_detection_settings") as batch_op:
            batch_op.drop_column("event_min_interval_ms")
