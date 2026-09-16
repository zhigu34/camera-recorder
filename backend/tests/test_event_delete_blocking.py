from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.services.event_log import add_audit_event, add_event

BACKEND_DIR = Path(__file__).resolve().parents[1]
HISTORY_PROTECTED_REVISION = "20260916_0021"
EVENT_BLOCKING_REVISION = "20260916_0022"


def _database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _alembic(db_path: Path, revision: str) -> subprocess.CompletedProcess[str]:
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


@pytest.mark.asyncio
async def test_event_creation_requires_explicit_business_history_blocking() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            lifecycle = add_event(
                session,
                level="info",
                category="camera",
                code="camera.updated",
                message="camera configuration changed",
            )
            audit = add_audit_event(
                session,
                code="operations.camera_updated",
                message="camera configuration changed",
            )
            business = add_event(
                session,
                level="error",
                category="recording",
                code="recording.segment_processing_failed",
                message="recording processing failed",
                blocks_camera_delete=True,
            )
            await session.commit()

            assert lifecycle.blocks_camera_delete is False
            assert audit.blocks_camera_delete is False
            assert business.blocks_camera_delete is True
    finally:
        await engine.dispose()


def test_event_blocking_migration_conservatively_backfills_monitoring_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "events.db"
    _alembic(db_path, HISTORY_PROTECTED_REVISION)

    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO cameras (
                id, name, ip, rtsp_port, username, password_encrypted, rtsp_path,
                enabled, auto_record, timestamp_mode, status, connection_type
            ) VALUES (7, 'event-history-camera', '192.0.2.7', 554, 'admin', 'ciphertext', '/main',
                      1, 0, 'reconstruct', 'unknown', 'manual_rtsp')
            """
        )
        connection.execute(
            """
            INSERT INTO recordings (
                id, camera_id, mp4_path, status, health_status, ffprobe_ok,
                has_video, has_audio, warning_count, timestamp_warning_count,
                network_warning_count, upload_status
            ) VALUES (71, 7, '/tmp/history.mp4', 'ready', 'healthy', 1,
                      1, 1, 0, 0, 0, 'pending')
            """
        )
        rows = [
            (1, 7, None, "info", "audit", "operations.camera_updated"),
            (2, 7, None, "error", "camera", "camera.probe_failed"),
            (3, 7, None, "info", "recorder", "recorder.started"),
            (4, 7, None, "error", "recording", "recording.segment_processing_failed"),
            (5, 7, None, "error", "camera", "camera.offline"),
            (6, 7, 71, "info", "custom", "business.recording_annotation"),
            (7, 7, None, "info", "notification", "notification.camera_offline_email_sent"),
        ]
        connection.executemany(
            """
            INSERT INTO events (
                id, camera_id, recording_id, level, category, code, message
            ) VALUES (?, ?, ?, ?, ?, ?, 'legacy event')
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()

    _alembic(db_path, EVENT_BLOCKING_REVISION)

    connection = sqlite3.connect(db_path)
    try:
        values = connection.execute(
            "SELECT id, blocks_camera_delete FROM events ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    assert values == [
        (1, 0),  # audit event
        (2, 0),  # one-shot probe/lifecycle diagnostic
        (3, 0),  # recorder lifecycle
        (4, 1),  # recording processing history
        (5, 1),  # actual monitoring outage
        (6, 1),  # any event tied to a Recording is historical business evidence
        (7, 0),  # notification delivery is derivative, not monitoring history itself
    ]
