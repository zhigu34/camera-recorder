from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD = "20260916_0023"
HIK_CONNECTION_REVISION = "20260917_0024"


def _database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _alembic(db_path: Path, revision: str) -> None:
    env = os.environ.copy()
    env["CAMREC_DATABASE_URL"] = _database_url(db_path)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def test_0024_adds_empty_hik_config_without_backfilling_legacy_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "hik-config.db"
    _alembic(db_path, PREVIOUS_HEAD)

    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO cameras (
                id, name, ip, rtsp_port, username, password_encrypted, rtsp_path,
                sub_rtsp_path, enabled, auto_record, timestamp_mode, status,
                connection_type
            ) VALUES (
                51, 'legacy-hik', '192.0.2.51', 554, 'admin',
                'legacy-ciphertext', '/hik-sdk/main', '/hik-sdk/sub', 1, 0,
                'reconstruct', 'unknown', 'hik_sdk'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO hik_device_metadata (
                camera_id, sdk_port, channel, main_stream_type, sub_stream_type,
                device_serial, device_model, device_name
            ) VALUES (
                51, 8000, 2, 0, 1, 'SERIAL-51', 'DS-2CD-Test', 'Legacy Gate'
            )
            """
        )
        connection.commit()

        before_camera = tuple(
            connection.execute(
                """
                SELECT id, connection_type, ip, username, password_encrypted
                FROM cameras WHERE id = 51
                """
            ).fetchone()
        )
        before_metadata = tuple(
            connection.execute(
                """
                SELECT camera_id, sdk_port, channel, main_stream_type, sub_stream_type,
                       device_serial, device_model, device_name
                FROM hik_device_metadata WHERE camera_id = 51
                """
            ).fetchone()
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM camera_connections WHERE camera_id = 51"
        ).fetchone()[0] == 0

    _alembic(db_path, HIK_CONNECTION_REVISION)

    with _connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            HIK_CONNECTION_REVISION
        )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "hik_connection_configs" in tables
        assert connection.execute("SELECT COUNT(*) FROM hik_connection_configs").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM camera_connections WHERE camera_id = 51"
        ).fetchone()[0] == 0
        assert tuple(
            connection.execute(
                """
                SELECT id, connection_type, ip, username, password_encrypted
                FROM cameras WHERE id = 51
                """
            ).fetchone()
        ) == before_camera
        assert tuple(
            connection.execute(
                """
                SELECT camera_id, sdk_port, channel, main_stream_type, sub_stream_type,
                       device_serial, device_model, device_name
                FROM hik_device_metadata WHERE camera_id = 51
                """
            ).fetchone()
        ) == before_metadata
