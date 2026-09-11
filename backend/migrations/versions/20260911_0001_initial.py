"""initial camera recorder schema

Revision ID: 20260911_0001
Revises:
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260911_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "cameras" not in existing:
        op.create_table(
            "cameras",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("ip", sa.String(length=255), nullable=False),
            sa.Column("rtsp_port", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=128), nullable=False),
            sa.Column("password_encrypted", sa.String(length=1024), nullable=False),
            sa.Column("rtsp_path", sa.String(length=255), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("auto_record", sa.Boolean(), nullable=False),
            sa.Column("timestamp_mode", sa.String(length=32), nullable=False),
            sa.Column("video_codec", sa.String(length=32), nullable=True),
            sa.Column("video_profile", sa.String(length=64), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("fps_num", sa.Integer(), nullable=True),
            sa.Column("fps_den", sa.Integer(), nullable=True),
            sa.Column("pixel_format", sa.String(length=64), nullable=True),
            sa.Column("has_b_frames", sa.Integer(), nullable=True),
            sa.Column("video_time_base", sa.String(length=32), nullable=True),
            sa.Column("audio_codec", sa.String(length=32), nullable=True),
            sa.Column("audio_profile", sa.String(length=64), nullable=True),
            sa.Column("sample_rate", sa.Integer(), nullable=True),
            sa.Column("channels", sa.Integer(), nullable=True),
            sa.Column("audio_frame_samples", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_online_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )
        op.create_index("ix_cameras_name", "cameras", ["name"], unique=True)
        op.create_index("ix_cameras_ip", "cameras", ["ip"], unique=False)

    if "recordings" not in existing:
        op.create_table(
            "recordings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration", sa.Float(), nullable=True),
            sa.Column("source_mkv_path", sa.String(length=1024), nullable=True),
            sa.Column("mp4_path", sa.String(length=1024), nullable=False, unique=True),
            sa.Column("file_size", sa.BigInteger(), nullable=True),
            sa.Column("video_codec", sa.String(length=32), nullable=True),
            sa.Column("audio_codec", sa.String(length=32), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("fps", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("health_status", sa.String(length=32), nullable=False),
            sa.Column("ffprobe_ok", sa.Integer(), nullable=False),
            sa.Column("has_video", sa.Integer(), nullable=False),
            sa.Column("has_audio", sa.Integer(), nullable=False),
            sa.Column("warning_count", sa.Integer(), nullable=False),
            sa.Column("timestamp_warning_count", sa.Integer(), nullable=False),
            sa.Column("network_warning_count", sa.Integer(), nullable=False),
            sa.Column("upload_status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )
        op.create_index("ix_recordings_camera_id", "recordings", ["camera_id"], unique=False)

    if "upload_tasks" not in existing:
        op.create_table(
            "upload_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("recording_id", sa.Integer(), sa.ForeignKey("recordings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("remote_path", sa.String(length=1024), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("retry_count", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.UniqueConstraint("recording_id", name="uq_upload_task_recording"),
        )
        op.create_index("ix_upload_tasks_recording_id", "upload_tasks", ["recording_id"], unique=False)
        op.create_index("ix_upload_tasks_status", "upload_tasks", ["status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "upload_tasks" in existing:
        op.drop_table("upload_tasks")
    if "recordings" in existing:
        op.drop_table("recordings")
    if "cameras" in existing:
        op.drop_table("cameras")
