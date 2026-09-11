"""add event log

Revision ID: 20260911_0002
Revises: 20260911_0001
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260911_0002"
down_revision: Union[str, Sequence[str], None] = "20260911_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "events" in existing:
        return

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recording_id", sa.Integer(), sa.ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_events_camera_id", "events", ["camera_id"], unique=False)
    op.create_index("ix_events_recording_id", "events", ["recording_id"], unique=False)
    op.create_index("ix_events_level", "events", ["level"], unique=False)
    op.create_index("ix_events_category", "events", ["category"], unique=False)
    op.create_index("ix_events_code", "events", ["code"], unique=False)
    op.create_index("ix_events_created_at", "events", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if "events" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("events")
