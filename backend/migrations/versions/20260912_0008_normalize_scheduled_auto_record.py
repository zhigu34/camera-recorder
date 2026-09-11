"""normalize scheduled cameras to automatic recording

Revision ID: 20260912_0008
Revises: 20260911_0007
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260912_0008"
down_revision: str | None = "20260911_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Weekly schedules are automatic-recording policies. Older UI versions could
    # persist recording_schedule_enabled=true together with auto_record=false,
    # leaving a valid-looking schedule that could never become eligible to run.
    op.execute(
        "UPDATE cameras "
        "SET auto_record = 1 "
        "WHERE recording_schedule_enabled = 1 AND auto_record = 0"
    )


def downgrade() -> None:
    # The previous contradictory intent cannot be reconstructed safely.
    pass
