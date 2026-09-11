import sqlite3
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def _sqlite_path() -> Path:
    prefix = "sqlite+aiosqlite:///"
    assert settings.database_url.startswith(prefix)
    return Path(settings.database_url.removeprefix(prefix))


def test_adjacent_recording_crosses_days_and_skips_unavailable(tmp_path):
    camera_name = f"pytest-nav-{uuid.uuid4().hex[:10]}"
    current_path = tmp_path / "current.mp4"
    target_path = tmp_path / "remote-only.mp4"
    current_path.write_bytes(b"current")

    with TestClient(app) as client:
        camera_response = client.post(
            "/api/cameras",
            json={
                "name": camera_name,
                "ip": "192.0.2.120",
                "username": "admin",
                "password": "test-secret",
                "rtsp_path": "/ch1/main",
                "timestamp_mode": "native",
            },
        )
        assert camera_response.status_code == 201
        camera_id = camera_response.json()["id"]

        connection = sqlite3.connect(_sqlite_path())
        try:
            connection.execute("PRAGMA foreign_keys=ON")

            def insert_recording(started_at, ended_at, mp4_path, status, upload_status):
                cursor = connection.execute(
                    """
                    INSERT INTO recordings (
                        camera_id, started_at, ended_at, duration, mp4_path, file_size,
                        video_codec, audio_codec, width, height, fps,
                        status, health_status, ffprobe_ok, has_video, has_audio,
                        warning_count, timestamp_warning_count, network_warning_count,
                        upload_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        camera_id,
                        started_at,
                        ended_at,
                        600.0,
                        str(mp4_path),
                        1024,
                        "hevc",
                        "aac",
                        1920,
                        1080,
                        15.0,
                        status,
                        "healthy",
                        1,
                        1,
                        1,
                        0,
                        0,
                        0,
                        upload_status,
                    ),
                )
                return cursor.lastrowid

            current_id = insert_recording(
                "2026-09-11 23:50:00.000000",
                "2026-09-12 00:00:00.000000",
                current_path,
                "ready",
                "pending",
            )
            insert_recording(
                "2026-09-12 00:00:05.000000",
                "2026-09-12 00:10:05.000000",
                tmp_path / "missing.mp4",
                "deleted",
                "pending",
            )
            target_id = insert_recording(
                "2026-09-13 00:05:00.000000",
                "2026-09-13 00:15:00.000000",
                target_path,
                "deleted",
                "success",
            )
            connection.execute(
                """
                INSERT INTO upload_tasks (
                    recording_id, provider, remote_path, status, retry_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    "openlist_webdav",
                    "监控录像/测试/2026-09-13/remote-only.mp4",
                    "success",
                    0,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        response = client.get(
            f"/api/recordings/{current_id}/adjacent",
            params={"direction": "next"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["date"] == "2026-09-13"
        assert body["item"]["id"] == target_id
        assert body["item"]["playback"]["remote_available"] is True
        assert body["item"]["playback"]["source_kind"] == "openlist_stream"

        reverse = client.get(
            f"/api/recordings/{target_id}/adjacent",
            params={"direction": "previous"},
        )
        assert reverse.status_code == 200
        reverse_body = reverse.json()
        assert reverse_body["date"] == "2026-09-11"
        assert reverse_body["item"]["id"] == current_id

        delete_response = client.delete(f"/api/cameras/{camera_id}")
        assert delete_response.status_code == 204


def test_adjacent_recording_missing_id_is_404():
    with TestClient(app) as client:
        response = client.get(
            "/api/recordings/99999999/adjacent",
            params={"direction": "next"},
        )
    assert response.status_code == 404
