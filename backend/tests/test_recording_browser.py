import sqlite3
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import recordings as recordings_api
from app.core.config import settings
from app.main import app


def _sqlite_path() -> Path:
    prefix = "sqlite+aiosqlite:///"
    assert settings.database_url.startswith(prefix)
    return Path(settings.database_url.removeprefix(prefix))


def test_recording_browser_empty_day_shape(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    with TestClient(app) as client:
        response = client.get(
            "/api/recordings/browser",
            params={"camera_id": 99999999, "date": "2026-09-11"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["camera_id"] == 99999999
    assert body["date"] == "2026-09-11"
    assert body["timezone"] == "Asia/Shanghai"
    assert body["count"] == 0
    assert body["items"] == []


def test_recording_browser_includes_evening_local_timestamp(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    camera_name = f"pytest-browser-{uuid.uuid4().hex[:10]}"
    mp4_path = f"/tmp/{camera_name}_2026-09-11_18-30-00.mp4"

    with TestClient(app) as client:
        camera_response = client.post(
            "/api/cameras",
            json={
                "name": camera_name,
                "ip": "192.0.2.90",
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
            connection.execute(
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
                    "2026-09-11 18:30:00.000000",
                    "2026-09-11 18:40:00.000000",
                    600.0,
                    mp4_path,
                    1024,
                    "hevc",
                    "aac",
                    1920,
                    1080,
                    15.0,
                    "ready",
                    "healthy",
                    1,
                    1,
                    1,
                    0,
                    0,
                    0,
                    "pending",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        response = client.get(
            "/api/recordings/browser",
            params={"camera_id": camera_id, "date": "2026-09-11"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["items"][0]["started_at"] == "2026-09-11T18:30:00+08:00"
        assert body["items"][0]["video_codec"] == "hevc"

        calendar = client.get(
            "/api/recordings/calendar",
            params={"camera_id": camera_id, "month": "2026-09"},
        )
        assert calendar.status_code == 200
        calendar_body = calendar.json()
        assert calendar_body["month"] == "2026-09"
        assert calendar_body["days"] == [
            {
                "date": "2026-09-11",
                "count": 1,
                "total_duration": 600.0,
                "total_size": 1024,
                "remote_only": 0,
                "warning_count": 0,
            }
        ]

        delete_response = client.delete(f"/api/cameras/{camera_id}")
        assert delete_response.status_code == 204


def test_cloud_playback_can_restore_successfully_archived_recording(monkeypatch):
    camera_name = f"pytest-cloud-{uuid.uuid4().hex[:10]}"
    mp4_path = f"/tmp/{camera_name}_2026-09-10_10-00-00.mp4"
    captured = {}

    async def fake_start(recording_id, remote_path, runtime):
        captured["recording_id"] = recording_id
        captured["remote_path"] = remote_path
        return {"state": "downloading", "error": None}

    monkeypatch.setattr(recordings_api.cloud_playback_manager, "start", fake_start)

    with TestClient(app) as client:
        camera_response = client.post(
            "/api/cameras",
            json={
                "name": camera_name,
                "ip": "192.0.2.91",
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
                    "2026-09-10 10:00:00.000000",
                    "2026-09-10 10:10:00.000000",
                    600.0,
                    mp4_path,
                    2048,
                    "hevc",
                    "aac",
                    1920,
                    1080,
                    15.0,
                    "deleted",
                    "healthy",
                    1,
                    1,
                    1,
                    0,
                    0,
                    0,
                    "success",
                ),
            )
            recording_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO upload_tasks (
                    recording_id, provider, remote_path, status, retry_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    recording_id,
                    "openlist_webdav",
                    "监控录像/测试/2026-09-10/cloud.mp4",
                    "success",
                    0,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        response = client.post(f"/api/recordings/{recording_id}/cloud-playback")
        assert response.status_code == 200
        body = response.json()
        assert body["remote_available"] is True
        assert body["cloud_state"] == "downloading"
        assert captured == {
            "recording_id": recording_id,
            "remote_path": "监控录像/测试/2026-09-10/cloud.mp4",
        }

        delete_response = client.delete(f"/api/cameras/{camera_id}")
        assert delete_response.status_code == 204


def test_recording_calendar_rejects_invalid_month():
    with TestClient(app) as client:
        response = client.get(
            "/api/recordings/calendar",
            params={"camera_id": 1, "month": "2026-13"},
        )
    assert response.status_code == 422


def test_recording_browser_rejects_invalid_date():
    with TestClient(app) as client:
        response = client.get(
            "/api/recordings/browser",
            params={"camera_id": 1, "date": "not-a-date"},
        )

    assert response.status_code == 422


def test_missing_recording_playback_is_404():
    with TestClient(app) as client:
        response = client.get("/api/recordings/99999999/playback")

    assert response.status_code == 404


def test_missing_recording_live_proxy_is_404():
    with TestClient(app) as client:
        response = client.get("/api/recordings/99999999/proxy-live.mp4")

    assert response.status_code == 404
