"""classify events that block camera deletion

Revision ID: 20260916_0022
Revises: 20260916_0021
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0022"
down_revision: str | None = "20260916_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONITORING_CAMERA_CODES = (
    "camera.ffmpeg_start_failed",
    "camera.ffmpeg_exited",
    "camera.ffmpeg_failure_streak",
    "camera.ffmpeg_stable",
    "camera.connection_lost",
    "camera.offline",
    "camera.connection_restored",
    "camera.recovered",
)


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "blocks_camera_delete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    events = sa.table(
        "events",
        sa.column("recording_id", sa.Integer()),
        sa.column("category", sa.String()),
        sa.column("code", sa.String()),
        sa.column("blocks_camera_delete", sa.Boolean()),
    )
    op.execute(
        sa.update(events)
        .where(
            sa.or_(
                events.c.recording_id.is_not(None),
                events.c.category == "recording",
                events.c.code.in_(_MONITORING_CAMERA_CODES),
            )
        )
        .values(blocks_camera_delete=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("blocks_camera_delete")
