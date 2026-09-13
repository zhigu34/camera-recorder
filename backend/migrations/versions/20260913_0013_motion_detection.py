"""add motion detection persistence

Revision ID: 20260913_0013
Revises: 20260912_0012
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0013"
down_revision: str | None = "20260912_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "motion_detection_settings" not in existing:
        op.create_table(
            "motion_detection_settings",
            sa.Column(
                "camera_id",
                sa.Integer(),
                sa.ForeignKey("cameras.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sensitivity", sa.String(length=16), nullable=False, server_default="medium"),
            sa.Column("analysis_fps", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("analysis_width", sa.Integer(), nullable=False, server_default="640"),
            sa.Column("min_duration_ms", sa.Integer(), nullable=False, server_default="800"),
            sa.Column("merge_gap_ms", sa.Integer(), nullable=False, server_default="3000"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.CheckConstraint("analysis_fps >= 1 AND analysis_fps <= 10", name="ck_motion_settings_fps"),
            sa.CheckConstraint("analysis_width >= 320 AND analysis_width <= 1280", name="ck_motion_settings_width"),
            sa.CheckConstraint("min_duration_ms >= 100 AND min_duration_ms <= 10000", name="ck_motion_settings_duration"),
            sa.CheckConstraint("merge_gap_ms >= 0 AND merge_gap_ms <= 30000", name="ck_motion_settings_merge_gap"),
            sa.CheckConstraint("sensitivity IN ('low','medium','high')", name="ck_motion_settings_sensitivity"),
        )

    if "motion_zones" not in existing:
        op.create_table(
            "motion_zones",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "camera_id",
                sa.Integer(),
                sa.ForeignKey("cameras.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("polygon_json", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )
        op.create_index("ix_motion_zones_camera_id", "motion_zones", ["camera_id"], unique=False)

    existing = set(sa.inspect(bind).get_table_names())
    if "motion_events" not in existing:
        op.create_table(
            "motion_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "camera_id",
                sa.Integer(),
                sa.ForeignKey("cameras.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "zone_id",
                sa.Integer(),
                sa.ForeignKey("motion_zones.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "recording_id",
                sa.Integer(),
                sa.ForeignKey("recordings.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("peak_score", sa.Float(), nullable=True),
            sa.Column("snapshot_path", sa.String(length=1024), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )
        op.create_index("ix_motion_events_camera_id", "motion_events", ["camera_id"], unique=False)
        op.create_index("ix_motion_events_zone_id", "motion_events", ["zone_id"], unique=False)
        op.create_index("ix_motion_events_recording_id", "motion_events", ["recording_id"], unique=False)
        op.create_index("ix_motion_events_started_at", "motion_events", ["started_at"], unique=False)
        op.create_index("ix_motion_events_ended_at", "motion_events", ["ended_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "motion_events" in existing:
        op.drop_table("motion_events")
    existing = set(sa.inspect(bind).get_table_names())
    if "motion_zones" in existing:
        op.drop_table("motion_zones")
    existing = set(sa.inspect(bind).get_table_names())
    if "motion_detection_settings" in existing:
        op.drop_table("motion_detection_settings")
