"""add runtime system settings

Revision ID: 20260911_0004
Revises: 20260911_0003
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260911_0004"
down_revision: Union[str, Sequence[str], None] = "20260911_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "system_settings" in existing:
        return
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_name", sa.String(length=128), nullable=False, server_default="Camera Recorder"),
        sa.Column("segment_duration_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("remux_concurrency", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("rtsp_timeout_us", sa.Integer(), nullable=False, server_default="5000000"),
        sa.Column("auto_start_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("align_segments_to_clock", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("storage_warning_percent", sa.Float(), nullable=False, server_default="80"),
        sa.Column("storage_critical_percent", sa.Float(), nullable=False, server_default="90"),
        sa.Column("upload_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("upload_concurrency", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("upload_retry_max", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("webdav_url", sa.String(length=1024), nullable=False, server_default="http://openlist:5244/dav/115"),
        sa.Column("webdav_root", sa.String(length=512), nullable=False, server_default="监控录像"),
        sa.Column("webdav_username", sa.String(length=255), nullable=False, server_default="admin"),
        sa.Column("webdav_password_encrypted", sa.Text(), nullable=True),
        sa.Column("local_retention_hours", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "system_settings" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("system_settings")
