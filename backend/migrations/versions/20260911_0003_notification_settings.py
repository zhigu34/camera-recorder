"""add notification settings

Revision ID: 20260911_0003
Revises: 20260911_0002
"""

from alembic import op
import sqlalchemy as sa

revision = "20260911_0003"
down_revision = "20260911_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notification_settings" not in inspector.get_table_names():
        op.create_table(
            "notification_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("offline_alert_seconds", sa.Float(), nullable=False, server_default="60"),
            sa.Column("recovery_stable_seconds", sa.Float(), nullable=False, server_default="10"),
            sa.Column("notify_recovery", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("smtp_host", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
            sa.Column("smtp_username", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("smtp_password_encrypted", sa.Text(), nullable=True),
            sa.Column("smtp_from", sa.String(length=320), nullable=False, server_default=""),
            sa.Column("smtp_to", sa.Text(), nullable=False, server_default=""),
            sa.Column("smtp_use_ssl", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("smtp_starttls", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("smtp_timeout_seconds", sa.Float(), nullable=False, server_default="15"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.execute(
            sa.text(
                "INSERT INTO notification_settings "
                "(id, email_enabled, offline_alert_seconds, recovery_stable_seconds, notify_recovery, "
                "smtp_host, smtp_port, smtp_username, smtp_from, smtp_to, smtp_use_ssl, smtp_starttls, smtp_timeout_seconds) "
                "VALUES (1, 0, 60, 10, 1, '', 587, '', '', '', 0, 1, 15)"
            )
        )


def downgrade() -> None:
    op.drop_table("notification_settings")
