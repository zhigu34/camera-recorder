"""extend email notification profile

Revision ID: 20260912_0010
Revises: 20260912_0009
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0010"
down_revision: str | None = "20260912_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification_settings") as batch_op:
        batch_op.add_column(sa.Column("smtp_sender_name", sa.String(length=128), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("smtp_auth_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("smtp_recipients_json", sa.Text(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("email_attach_images", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("email_capture_interval_seconds", sa.Integer(), nullable=False, server_default="2"))


def downgrade() -> None:
    with op.batch_alter_table("notification_settings") as batch_op:
        batch_op.drop_column("email_capture_interval_seconds")
        batch_op.drop_column("email_attach_images")
        batch_op.drop_column("smtp_recipients_json")
        batch_op.drop_column("smtp_auth_enabled")
        batch_op.drop_column("smtp_sender_name")
