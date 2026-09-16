from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
LEGACY_REVISION = "20260916_0019"
PHASE1_HEAD = "20260916_0022"


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


def test_fresh_sqlite_upgrades_to_phase1_head(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    _alembic(db_path, PHASE1_HEAD)

    with _connect(db_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert revision == PHASE1_HEAD

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"camera_connections", "rtsp_connection_configs"} <= tables

        event_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(events)")
        }
        assert "blocks_camera_delete" in event_columns


def test_upgrade_from_0019_to_head_preserves_camera_identity_and_history(tmp_path: Path) -> None:
    db_path = tmp_path / "upgrade.db"
    _alembic(db_path, LEGACY_REVISION)

    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO cameras (
                id, name, ip, rtsp_port, username, password_encrypted, rtsp_path,
                sub_rtsp_path, enabled, auto_record, timestamp_mode, status,
                connection_type
            ) VALUES (
                17, 'phase1-camera', '192.0.2.17', 8554, 'operator',
                'ciphertext-phase1-must-not-change', '/main', '/sub',
                1, 0, 'reconstruct', 'online', 'manual_rtsp'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO recordings (
                id, camera_id, mp4_path, status, health_status, ffprobe_ok,
                has_video, has_audio, warning_count, timestamp_warning_count,
                network_warning_count, upload_status
            ) VALUES (
                171, 17, '/tmp/phase1-history.mp4', 'ready', 'healthy', 1,
                1, 1, 0, 0, 0, 'pending'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO motion_events (
                id, camera_id, started_at, ended_at, peak_score
            ) VALUES (
                172, 17, '2026-09-16 10:00:00', '2026-09-16 10:00:05', 0.8
            )
            """
        )
        connection.execute(
            """
            INSERT INTO camera_health_samples (
                id, camera_id, state, expected_recording, online, recorder_ok,
                restart_count, timestamp_warning_count, network_warning_count
            ) VALUES (173, 17, 'RECORDING', 1, 1, 1, 0, 0, 0)
            """
        )
        connection.execute(
            """
            INSERT INTO events (
                id, camera_id, recording_id, level, category, code, message
            ) VALUES (
                174, 17, 171, 'warning', 'recording',
                'recording.legacy_history', 'legacy monitoring history'
            )
            """
        )
        connection.commit()

        before = {
            "cameras": [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, password_encrypted FROM cameras ORDER BY id"
                )
            ],
            "recordings": [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, camera_id FROM recordings ORDER BY id"
                )
            ],
            "motion_events": [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, camera_id FROM motion_events ORDER BY id"
                )
            ],
            "health_samples": [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, camera_id FROM camera_health_samples ORDER BY id"
                )
            ],
            "events": [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, camera_id, recording_id FROM events ORDER BY id"
                )
            ],
        }

    _alembic(db_path, PHASE1_HEAD)

    with _connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PHASE1_HEAD
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT id, password_encrypted FROM cameras ORDER BY id"
            )
        ] == before["cameras"]
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT id, camera_id FROM recordings ORDER BY id"
            )
        ] == before["recordings"]
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT id, camera_id FROM motion_events ORDER BY id"
            )
        ] == before["motion_events"]
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT id, camera_id FROM camera_health_samples ORDER BY id"
            )
        ] == before["health_samples"]
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT id, camera_id, recording_id FROM events ORDER BY id"
            )
        ] == before["events"]

        connections = connection.execute(
            """
            SELECT camera_id, adapter, host, username, password_encrypted, revision,
                   verification_status
            FROM camera_connections
            ORDER BY camera_id
            """
        ).fetchall()
        assert [tuple(row) for row in connections] == [
            (
                17,
                "manual_rtsp",
                "192.0.2.17",
                "operator",
                "ciphertext-phase1-must-not-change",
                1,
                "unverified",
            )
        ]

        rtsp = connection.execute(
            """
            SELECT c.camera_id, r.port, r.main_path, r.sub_path
            FROM rtsp_connection_configs AS r
            JOIN camera_connections AS c ON c.id = r.connection_id
            """
        ).fetchone()
        assert tuple(rtsp) == (17, 8554, "/main", "/sub")

        assert connection.execute(
            "SELECT blocks_camera_delete FROM events WHERE id = 174"
        ).fetchone()[0] == 1
