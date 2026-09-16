"""protect camera history from cascade deletion

Revision ID: 20260916_0021
Revises: 20260916_0020
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0021"
down_revision: str | None = "20260916_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}
_HISTORY_TABLES = (
    "motion_events",
    "recordings",
    "camera_health_samples",
)


def _camera_fk_name(table_name: str) -> str:
    return f"fk_{table_name}_camera_id_cameras"


def _replace_camera_fk(table_name: str, *, ondelete: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        raise RuntimeError(f"expected history table is missing: {table_name}")

    camera_fk = next(
        (
            foreign_key
            for foreign_key in inspector.get_foreign_keys(table_name)
            if foreign_key.get("constrained_columns") == ["camera_id"]
            and foreign_key.get("referred_table") == "cameras"
        ),
        None,
    )
    if camera_fk is None:
        raise RuntimeError(f"expected camera history foreign key is missing: {table_name}.camera_id")

    existing_name = camera_fk.get("name") or _camera_fk_name(table_name)
    with op.batch_alter_table(
        table_name,
        recreate="always",
        naming_convention=_FK_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(existing_name, type_="foreignkey")
        batch_op.create_foreign_key(
            _camera_fk_name(table_name),
            "cameras",
            ["camera_id"],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    for table_name in _HISTORY_TABLES:
        _replace_camera_fk(table_name, ondelete="RESTRICT")


def downgrade() -> None:
    for table_name in _HISTORY_TABLES:
        _replace_camera_fk(table_name, ondelete="CASCADE")
