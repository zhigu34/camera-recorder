from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
LEGACY_REVISION = "20260916_0019"
CONNECTION_REVISION = "20260916_0020"


def _database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _alembic(db_path: Path, revision: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CAMREC_DATABASE_URL"] = _database_url(db_path)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _insert_camera(
    connection: sqlite3.Connection,
    *,
    camera_id: int,
    name: str,
    connection_type: str = "manual_rtsp",
    host: str = "10.0.0.10",
    port: int = 8554,
    username: str = "operator",
    ciphertext: str = "ciphertext-must-not-change",
    main_path: str = "/main",
    sub_path: str | None = "/sub",
) -> None:
    connection.execute(
        """
        INSERT INTO cameras (
            id, name, ip, rtsp_port, username, password_encrypted, rtsp_path,
            sub_rtsp_path, enabled, auto_record, timestamp_mode, status,
            connection_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 'reconstruct', 'unknown', ?)
        """,
        (
            camera_id,
            name,
            host,
            port,
            username,
            ciphertext,
            main_path,
            sub_path,
            connection_type,
        ),
    )


def test_migration_backfills_rtsp_connections_without_changing_camera_identity_or_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "camera.db"
    _alembic(db_path, LEGACY_REVISION)

    with _connect(db_path) as connection:
        _insert_camera(
            connection,
            camera_id=7,
            name="warehouse-east",
            host="10.20.0.7",
            port=9554,
            ciphertext="encrypted-value-7",
            main_path="/Streaming/Channels/101",
            sub_path="/Streaming/Channels/102",
        )
        _insert_camera(
            connection,
            camera_id=23,
            name="warehouse-west",
            host="10.20.0.23",
            port=554,
            username="viewer",
            ciphertext="encrypted-value-23",
            main_path="/live/main",
            sub_path=None,
        )
        connection.execute(
            """
            INSERT INTO camera_health_samples (
                id, camera_id, state, expected_recording, online, recorder_ok,
                restart_count, timestamp_warning_count, network_warning_count
            ) VALUES (91, 7, 'online', 1, 1, 1, 0, 0, 0)
            """
        )
        connection.commit()

        before_cameras = [
            tuple(row)
            for row in connection.execute(
                """
                SELECT id, name, ip, rtsp_port, username, password_encrypted,
                       rtsp_path, sub_rtsp_path, connection_type
                FROM cameras ORDER BY id
                """
            )
        ]
        before_health = tuple(
            connection.execute(
                "SELECT id, camera_id, state FROM camera_health_samples WHERE id = 91"
            ).fetchone()
        )

    _alembic(db_path, CONNECTION_REVISION)

    with _connect(db_path) as connection:
        after_cameras = [
            tuple(row)
            for row in connection.execute(
                """
                SELECT id, name, ip, rtsp_port, username, password_encrypted,
                       rtsp_path, sub_rtsp_path, connection_type
                FROM cameras ORDER BY id
                """
            )
        ]
        assert after_cameras == before_cameras
        assert tuple(
            connection.execute(
                "SELECT id, camera_id, state FROM camera_health_samples WHERE id = 91"
            ).fetchone()
        ) == before_health

        connections = connection.execute(
            """
            SELECT id, camera_id, adapter, host, username, password_encrypted,
                   revision, verification_status
            FROM camera_connections ORDER BY camera_id
            """
        ).fetchall()
        assert len(connections) == 2
        assert [row["camera_id"] for row in connections] == [7, 23]
        assert all(row["adapter"] == "manual_rtsp" for row in connections)
        assert all(row["revision"] == 1 for row in connections)
        assert all(row["verification_status"] == "unverified" for row in connections)
        assert connections[0]["host"] == "10.20.0.7"
        assert connections[0]["username"] == "operator"
        assert connections[0]["password_encrypted"] == "encrypted-value-7"
        assert connections[1]["password_encrypted"] == "encrypted-value-23"

        rtsp_rows = connection.execute(
            """
            SELECT c.camera_id, r.port, r.main_path, r.sub_path
            FROM rtsp_connection_configs AS r
            JOIN camera_connections AS c ON c.id = r.connection_id
            ORDER BY c.camera_id
            """
        ).fetchall()
        assert [tuple(row) for row in rtsp_rows] == [
            (7, 9554, "/Streaming/Channels/101", "/Streaming/Channels/102"),
            (23, 554, "/live/main", None),
        ]

        duplicate_count = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT camera_id FROM camera_connections
                GROUP BY camera_id HAVING COUNT(*) != 1
            )
            """
        ).fetchone()[0]
        assert duplicate_count == 0


def test_migration_aborts_and_reports_unexpected_legacy_adapter(tmp_path: Path) -> None:
    db_path = tmp_path / "camera.db"
    _alembic(db_path, LEGACY_REVISION)

    with _connect(db_path) as connection:
        _insert_camera(
            connection,
            camera_id=44,
            name="unexpected-onvif",
            connection_type="onvif",
        )
        connection.commit()

    result = _alembic(db_path, CONNECTION_REVISION, check=False)
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode != 0
    assert "44" in output
    assert "manual_rtsp" in output

    with _connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cameras").fetchone()[0] == 1
        # A failed preflight must not leave a partially backfilled schema behind.
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "camera_connections" not in tables
        assert "rtsp_connection_configs" not in tables
