"""add native detection events and ONVIF event settings

Revision ID: 20260918_0027
Revises: 20260918_0026
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_0027"
down_revision: str | None = "20260918_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "onvif_event_settings",
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("camera_id"),
    )
    op.create_table(
        "detection_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_detection_events_camera_id", "detection_events", ["camera_id"])
    op.create_index("ix_detection_events_recording_id", "detection_events", ["recording_id"])
    op.create_index("ix_detection_events_source_kind", "detection_events", ["source_kind"])
    op.create_index("ix_detection_events_provider", "detection_events", ["provider"])
    op.create_index("ix_detection_events_event_type", "detection_events", ["event_type"])
    op.create_index("ix_detection_events_started_at", "detection_events", ["started_at"])
    op.create_index("ix_detection_events_ended_at", "detection_events", ["ended_at"])
    op.create_index("ix_detection_events_created_at", "detection_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_detection_events_created_at", table_name="detection_events")
    op.drop_index("ix_detection_events_ended_at", table_name="detection_events")
    op.drop_index("ix_detection_events_started_at", table_name="detection_events")
    op.drop_index("ix_detection_events_event_type", table_name="detection_events")
    op.drop_index("ix_detection_events_provider", table_name="detection_events")
    op.drop_index("ix_detection_events_source_kind", table_name="detection_events")
    op.drop_index("ix_detection_events_recording_id", table_name="detection_events")
    op.drop_index("ix_detection_events_camera_id", table_name="detection_events")
    op.drop_table("detection_events")
    op.drop_table("onvif_event_settings")
