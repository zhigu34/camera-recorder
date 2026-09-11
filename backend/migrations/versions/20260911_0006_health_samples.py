"""add camera health samples

Revision ID: 20260911_0006
Revises: 20260911_0005
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0006"
down_revision: str | None = "20260911_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "camera_health_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("expected_recording", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("online", sa.Boolean(), nullable=True),
        sa.Column("recorder_ok", sa.Boolean(), nullable=True),
        sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timestamp_warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("network_warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_camera_health_samples_camera_id", "camera_health_samples", ["camera_id"])
    op.create_index("ix_camera_health_samples_sampled_at", "camera_health_samples", ["sampled_at"])
    op.create_index(
        "ix_camera_health_samples_camera_time",
        "camera_health_samples",
        ["camera_id", "sampled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_camera_health_samples_camera_time", table_name="camera_health_samples")
    op.drop_index("ix_camera_health_samples_sampled_at", table_name="camera_health_samples")
    op.drop_index("ix_camera_health_samples_camera_id", table_name="camera_health_samples")
    op.drop_table("camera_health_samples")
