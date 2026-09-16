"""migrate legacy RTSP cameras to current connections

Revision ID: 20260916_0020
Revises: 20260916_0019
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0020"
down_revision: str | None = "20260916_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXPECTED_LEGACY_ADAPTER = "manual_rtsp"


def _legacy_cameras(bind: sa.Connection) -> list[dict[str, object]]:
    rows = bind.execute(
        sa.text(
            """
            SELECT id, connection_type, ip, rtsp_port, username, password_encrypted,
                   rtsp_path, sub_rtsp_path
            FROM cameras
            ORDER BY id
            """
        )
    ).mappings()
    return [dict(row) for row in rows]


def _guard_legacy_adapters(cameras: list[dict[str, object]]) -> None:
    offenders = [
        int(camera["id"])
        for camera in cameras
        if camera["connection_type"] != _EXPECTED_LEGACY_ADAPTER
    ]
    if offenders:
        camera_ids = ", ".join(str(camera_id) for camera_id in offenders)
        raise RuntimeError(
            "Camera connection migration only accepts legacy "
            f"connection_type='{_EXPECTED_LEGACY_ADAPTER}'; "
            f"offending camera IDs: {camera_ids}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "cameras" not in tables:
        return

    cameras = _legacy_cameras(bind)
    _guard_legacy_adapters(cameras)

    if "camera_connections" in tables or "rtsp_connection_configs" in tables:
        raise RuntimeError(
            "Camera connection migration found an unexpected partial schema; "
            "camera_connections and rtsp_connection_configs must not exist before upgrade"
        )

    op.create_table(
        "camera_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("adapter", sa.String(length=32), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_encrypted", sa.String(length=1024), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            server_default="unverified",
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_camera_connections_camera_id"),
        "camera_connections",
        ["camera_id"],
        unique=True,
    )

    op.create_table(
        "rtsp_connection_configs",
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("port", sa.Integer(), server_default="554", nullable=False),
        sa.Column("main_path", sa.String(length=255), nullable=False),
        sa.Column("sub_path", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["camera_connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("connection_id"),
    )

    if not cameras:
        return

    camera_connections = sa.table(
        "camera_connections",
        sa.column("camera_id", sa.Integer()),
        sa.column("adapter", sa.String()),
        sa.column("host", sa.String()),
        sa.column("username", sa.String()),
        sa.column("password_encrypted", sa.String()),
        sa.column("revision", sa.Integer()),
        sa.column("verification_status", sa.String()),
    )
    op.bulk_insert(
        camera_connections,
        [
            {
                "camera_id": camera["id"],
                "adapter": _EXPECTED_LEGACY_ADAPTER,
                "host": camera["ip"],
                "username": camera["username"],
                "password_encrypted": camera["password_encrypted"],
                "revision": 1,
                "verification_status": "unverified",
            }
            for camera in cameras
        ],
    )

    connection_ids = {
        int(row.camera_id): int(row.id)
        for row in bind.execute(
            sa.text("SELECT id, camera_id FROM camera_connections ORDER BY camera_id")
        )
    }
    rtsp_configs = sa.table(
        "rtsp_connection_configs",
        sa.column("connection_id", sa.Integer()),
        sa.column("port", sa.Integer()),
        sa.column("main_path", sa.String()),
        sa.column("sub_path", sa.String()),
    )
    op.bulk_insert(
        rtsp_configs,
        [
            {
                "connection_id": connection_ids[int(camera["id"])],
                "port": camera["rtsp_port"],
                "main_path": camera["rtsp_path"],
                "sub_path": camera["sub_rtsp_path"],
            }
            for camera in cameras
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "rtsp_connection_configs" in tables:
        op.drop_table("rtsp_connection_configs")
    if "camera_connections" in tables:
        op.drop_table("camera_connections")
