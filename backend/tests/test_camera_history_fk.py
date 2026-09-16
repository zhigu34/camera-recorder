from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.models import Camera

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _alembic(db_path: Path, revision: str = "head") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CAMREC_DATABASE_URL"] = _database_url(db_path)
    return subprocess.run(
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


def _insert_camera(connection: sqlite3.Connection, camera_id: int) -> None:
    connection.execute(
        """
        INSERT INTO cameras (
            id, name, ip, rtsp_port, username, password_encrypted, rtsp_path,
            enabled, auto_record, timestamp_mode, status, connection_type
        ) VALUES (?, ?, '192.0.2.10', 554, 'admin', 'ciphertext', '/main',
                  1, 0, 'reconstruct', 'unknown', 'manual_rtsp')
        """,
        (camera_id, f"history-camera-{camera_id}"),
    )


def _insert_recording(connection: sqlite3.Connection, camera_id: int) -> None:
    connection.execute(
        """
        INSERT INTO recordings (
            id, camera_id, mp4_path, status, health_status, ffprobe_ok,
            has_video, has_audio, warning_count, timestamp_warning_count,
            network_warning_count, upload_status
        ) VALUES (101, ?, '/tmp/history.mp4', 'ready', 'healthy', 1,
                  1, 1, 0, 0, 0, 'pending')
        """,
        (camera_id,),
    )


def _insert_motion_event(connection: sqlite3.Connection, camera_id: int) -> None:
    connection.execute(
        """
        INSERT INTO motion_events (
            id, camera_id, started_at, ended_at, peak_score
        ) VALUES (102, ?, '2026-09-16 09:00:00', '2026-09-16 09:00:05', 0.8)
        """,
        (camera_id,),
    )


def _insert_health_sample(connection: sqlite3.Connection, camera_id: int) -> None:
    connection.execute(
        """
        INSERT INTO camera_health_samples (
            id, camera_id, state, expected_recording, online, recorder_ok,
            restart_count, timestamp_warning_count, network_warning_count
        ) VALUES (103, ?, 'online', 1, 1, 1, 0, 0, 0)
        """,
        (camera_id,),
    )


@pytest.mark.parametrize(
    ("history_table", "insert_history"),
    [
        ("recordings", _insert_recording),
        ("motion_events", _insert_motion_event),
        ("camera_health_samples", _insert_health_sample),
    ],
)
def test_camera_delete_is_blocked_by_each_history_table(
    tmp_path: Path,
    history_table: str,
    insert_history,
) -> None:
    db_path = tmp_path / f"{history_table}.db"
    _alembic(db_path)

    with _connect(db_path) as connection:
        _insert_camera(connection, 7)
        insert_history(connection, 7)
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM cameras WHERE id = 7")
        connection.rollback()

        assert connection.execute("SELECT COUNT(*) FROM cameras WHERE id = 7").fetchone()[0] == 1
        assert connection.execute(
            f"SELECT COUNT(*) FROM {history_table} WHERE camera_id = 7"
        ).fetchone()[0] == 1


def test_camera_recording_relationship_never_cascades_history_delete() -> None:
    cascade = Camera.recordings.property.cascade

    assert "delete" not in cascade
    assert "delete-orphan" not in cascade
