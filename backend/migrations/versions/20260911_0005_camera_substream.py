"""add camera substream path

Revision ID: 20260911_0005
Revises: 20260911_0004
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0005"
down_revision: str | None = "20260911_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("sub_rtsp_path", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "sub_rtsp_path")
