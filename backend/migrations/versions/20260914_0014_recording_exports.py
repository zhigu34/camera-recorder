"""add recording export persistence

Revision ID: 20260914_0014
Revises: 20260913_0013
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0014"
down_revision: str | None = "20260913_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "export_jobs" not in existing:
        op.create_table(
            "export_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "camera_id",
                sa.Integer(),
                sa.ForeignKey("cameras.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("requested_start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("requested_end_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("export_mode", sa.String(length=16), nullable=False, server_default="fast"),
            sa.Column("gap_policy", sa.String(length=16), nullable=False, server_default="merge"),
            sa.Column(
                "package_mode", sa.String(length=16), nullable=False, server_default="individual"
            ),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
            sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requested_duration", sa.Float(), nullable=False),
            sa.Column("covered_duration", sa.Float(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("export_mode IN ('fast','exact')", name="ck_export_jobs_mode"),
            sa.CheckConstraint("gap_policy IN ('merge','split')", name="ck_export_jobs_gap_policy"),
            sa.CheckConstraint(
                "package_mode IN ('individual','zip')", name="ck_export_jobs_package_mode"
            ),
            sa.CheckConstraint(
                "status IN ('pending','processing','ready','failed','expired')",
                name="ck_export_jobs_status",
            ),
        )
        op.create_index("ix_export_jobs_camera_id", "export_jobs", ["camera_id"], unique=False)
        op.create_index("ix_export_jobs_status", "export_jobs", ["status"], unique=False)
        op.create_index("ix_export_jobs_expires_at", "export_jobs", ["expires_at"], unique=False)

    existing = set(sa.inspect(bind).get_table_names())
    if "export_artifacts" not in existing:
        op.create_table(
            "export_artifacts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "export_job_id",
                sa.Integer(),
                sa.ForeignKey("export_jobs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("segment_index", sa.Integer(), nullable=True),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("path", sa.String(length=2048), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.CheckConstraint("kind IN ('mp4','zip','manifest')", name="ck_export_artifacts_kind"),
        )
        op.create_index(
            "ix_export_artifacts_export_job_id", "export_artifacts", ["export_job_id"], unique=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "export_artifacts" in existing:
        op.drop_table("export_artifacts")
    existing = set(sa.inspect(bind).get_table_names())
    if "export_jobs" in existing:
        op.drop_table("export_jobs")
