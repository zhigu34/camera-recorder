"""extend email notification profile

Revision ID: 20260912_0010
Revises: 20260912_0009
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260912_0010"
down_revision = "20260912_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_settings",
        sa.Column("smtp_sender_name", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "notification_settings",
        sa.Column("smtp_auth_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "notification_settings",
        sa.Column("smtp_recipients_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "notification_settings",
        sa.Column("email_attach_images", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "notification_settings",
        sa.Column("email_capture_interval_seconds", sa.Integer(), nullable=False, server_default="2"),
    )


def downgrade() -> None:
    op.drop_column("notification_settings", "email_capture_interval_seconds")
    op.drop_column("notification_settings", "email_attach_images")
    op.drop_column("notification_settings", "smtp_recipients_json")
    op.drop_column("notification_settings", "smtp_auth_enabled")
    op.drop_column("notification_settings", "smtp_sender_name")
