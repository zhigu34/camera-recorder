"""preserve legacy unauthenticated SMTP settings

Revision ID: 20260912_0011
Revises: 20260912_0010
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260912_0011"
down_revision: str | None = "20260912_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Before smtp_auth_enabled existed, SMTP AUTH was only attempted when a
    # username was configured. Keep that behavior for legacy rows so an
    # unauthenticated SMTP relay does not become "unconfigured" after upgrade.
    op.execute(
        """
        UPDATE notification_settings
        SET smtp_auth_enabled = 0
        WHERE TRIM(COALESCE(smtp_username, '')) = ''
        """
    )


def downgrade() -> None:
    # No data rollback: smtp_auth_enabled is a user preference once introduced.
    pass
