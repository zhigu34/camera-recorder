from __future__ import annotations

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


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_sqlite_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _create_camera(client: TestClient, prefix: str) -> int:
    response = client.post(
        "/api/cameras",
        json={
            "name": f"{prefix}-{uuid.uuid4().hex[:10]}",
            "ip": "192.0.2.150",
            "username": "admin",
            "password": "test-secret",
            "rtsp_path": "/ch1/main",
            "timestamp_mode": "native",
            "enabled": False,
        },
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def _camera_exists(client: TestClient, camera_id: int) -> bool:
    return client.get(f"/api/cameras/{camera_id}").status_code == 200


def _clear_camera_history(camera_id: int) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM motion_events WHERE camera_id = ?", (camera_id,))
        connection.execute("DELETE FROM detection_events WHERE camera_id = ?", (camera_id,))
        connection.execute("DELETE FROM camera_health_samples WHERE camera_id = ?", (camera_id,))
        connection.execute(
            "DELETE FROM events WHERE camera_id = ? AND blocks_camera_delete = 1",
            (camera_id,),
        )
        connection.execute(
            """
            DELETE FROM upload_tasks
            WHERE recording_id IN (
                SELECT id FROM recordings WHERE camera_id = ?
            )
            """,
            (camera_id,),
        )
        connection.execute("DELETE FROM recordings WHERE camera_id = ?", (camera_id,))
        connection.commit()


def _cleanup_camera(client: TestClient, camera_id: int) -> None:
    if not _camera_exists(client, camera_id):
        return
    _clear_camera_history(camera_id)
    response = client.delete(f"/api/cameras/{camera_id}")
    assert response.status_code == 204


def _assert_zero_impact(payload: dict, camera_id: int) -> None:
    assert payload == {
        "camera_id": camera_id,
        "recordings": 0,
        "motion_events": 0,
        "detection_events": 0,
        "health_samples": 0,
        "blocking_events": 0,
        "pending_uploads": 0,
        "can_delete": True,
    }


def test_camera_deletion_service_is_available() -> None:
    from app.services.camera_deletion import camera_deletion_impact

    assert callable(camera_deletion_impact)


def test_empty_camera_reports_no_impact_and_can_be_deleted() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        camera_id = _create_camera(client, "pytest-delete-empty")
        try:
            impact_response = client.get(f"/api/cameras/{camera_id}/deletion-impact")
            assert impact_response.status_code == 200
            _assert_zero_impact(impact_response.json(), camera_id)

            delete_response = client.delete(f"/api/cameras/{camera_id}")
            assert delete_response.status_code == 204
            assert client.get(f"/api/cameras/{camera_id}").status_code == 404
        finally:
            _cleanup_camera(client, camera_id)


def test_recorded_camera_refuses_delete_and_reports_pending_upload() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        camera_id = _create_camera(client, "pytest-delete-recording")
        try:
            with _connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO recordings (
                        camera_id, mp4_path, status, health_status, ffprobe_ok,
                        has_video, has_audio, warning_count, timestamp_warning_count,
                        network_warning_count, upload_status
                    ) VALUES (?, ?, 'ready', 'healthy', 1, 1, 1, 0, 0, 0, 'pending')
                    """,
                    (camera_id, f"/tmp/delete-impact-{camera_id}.mp4"),
                )
                recording_id = int(cursor.lastrowid)
                connection.execute(
                    """
                    INSERT INTO upload_tasks (
                        recording_id, provider, remote_path, status, retry_count
                    ) VALUES (?, 'openlist_webdav', ?, 'pending', 0)
                    """,
                    (recording_id, f"camera-{camera_id}/pending.mp4"),
                )
                connection.commit()

            impact_response = client.get(f"/api/cameras/{camera_id}/deletion-impact")
            assert impact_response.status_code == 200
            impact = impact_response.json()
            assert impact["recordings"] == 1
            assert impact["pending_uploads"] == 1
            assert impact["motion_events"] == 0
            assert impact["detection_events"] == 0
            assert impact["health_samples"] == 0
            assert impact["blocking_events"] == 0
            assert impact["can_delete"] is False

            delete_response = client.delete(f"/api/cameras/{camera_id}")
            assert delete_response.status_code == 409
            assert delete_response.json()["detail"] == impact
            assert _camera_exists(client, camera_id)
        finally:
            _cleanup_camera(client, camera_id)


def test_motion_history_alone_refuses_camera_delete() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        camera_id = _create_camera(client, "pytest-delete-motion")
        try:
            with _connect() as connection:
                connection.execute(
                    """
                    INSERT INTO motion_events (
                        camera_id, started_at, ended_at, peak_score
                    ) VALUES (?, '2026-09-16 10:00:00', '2026-09-16 10:00:05', 0.8)
                    """,
                    (camera_id,),
                )
                connection.commit()

            impact = client.get(f"/api/cameras/{camera_id}/deletion-impact").json()
            assert impact["motion_events"] == 1
            assert impact["can_delete"] is False

            delete_response = client.delete(f"/api/cameras/{camera_id}")
            assert delete_response.status_code == 409
            assert delete_response.json()["detail"] == impact
        finally:
            _cleanup_camera(client, camera_id)


def test_health_history_alone_refuses_camera_delete() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        camera_id = _create_camera(client, "pytest-delete-health")
        try:
            with _connect() as connection:
                connection.execute(
                    """
                    INSERT INTO camera_health_samples (
                        camera_id, state, expected_recording, online, recorder_ok,
                        restart_count, timestamp_warning_count, network_warning_count
                    ) VALUES (?, 'online', 1, 1, 1, 0, 0, 0)
                    """,
                    (camera_id,),
                )
                connection.commit()

            impact = client.get(f"/api/cameras/{camera_id}/deletion-impact").json()
            assert impact["health_samples"] == 1
            assert impact["can_delete"] is False

            delete_response = client.delete(f"/api/cameras/{camera_id}")
            assert delete_response.status_code == 409
            assert delete_response.json()["detail"] == impact
        finally:
            _cleanup_camera(client, camera_id)


def test_blocking_business_event_refuses_camera_delete() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        camera_id = _create_camera(client, "pytest-delete-event")
        try:
            with _connect() as connection:
                connection.execute(
                    """
                    INSERT INTO events (
                        camera_id, level, category, code, message, blocks_camera_delete
                    ) VALUES (?, 'error', 'camera', 'camera.offline', 'offline history', 1)
                    """,
                    (camera_id,),
                )
                connection.commit()

            impact = client.get(f"/api/cameras/{camera_id}/deletion-impact").json()
            assert impact["blocking_events"] == 1
            assert impact["can_delete"] is False

            delete_response = client.delete(f"/api/cameras/{camera_id}")
            assert delete_response.status_code == 409
            assert delete_response.json()["detail"] == impact
        finally:
            _cleanup_camera(client, camera_id)


def test_nonblocking_audit_event_does_not_prevent_delete_and_is_preserved() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        camera_id = _create_camera(client, "pytest-delete-audit")
        audit_id: int | None = None
        try:
            with _connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO events (
                        camera_id, level, category, code, message, blocks_camera_delete
                    ) VALUES (?, 'info', 'audit', 'operations.test_audit', 'audit history', 0)
                    """,
                    (camera_id,),
                )
                audit_id = int(cursor.lastrowid)
                connection.commit()

            impact_response = client.get(f"/api/cameras/{camera_id}/deletion-impact")
            assert impact_response.status_code == 200
            _assert_zero_impact(impact_response.json(), camera_id)

            delete_response = client.delete(f"/api/cameras/{camera_id}")
            assert delete_response.status_code == 204

            with _connect() as connection:
                row = connection.execute(
                    "SELECT camera_id, blocks_camera_delete FROM events WHERE id = ?",
                    (audit_id,),
                ).fetchone()
                assert row is not None
                assert row["camera_id"] is None
                assert row["blocks_camera_delete"] == 0
        finally:
            _cleanup_camera(client, camera_id)
            if audit_id is not None:
                with _connect() as connection:
                    connection.execute("DELETE FROM events WHERE id = ?", (audit_id,))
                    connection.commit()



def test_native_detection_history_alone_refuses_camera_delete() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        camera_id = _create_camera(client, "pytest-delete-native-detection")
        try:
            with _connect() as connection:
                connection.execute(
                    """
                    INSERT INTO detection_events (
                        camera_id, source_kind, provider, event_type,
                        started_at, ended_at, metadata_json
                    ) VALUES (
                        ?, 'camera_native', 'onvif', 'person',
                        '2026-09-18 10:00:00', '2026-09-18 10:00:00', '{}'
                    )
                    """,
                    (camera_id,),
                )
                connection.commit()

            impact = client.get(f"/api/cameras/{camera_id}/deletion-impact").json()
            assert impact["detection_events"] == 1
            assert impact["can_delete"] is False

            delete_response = client.delete(f"/api/cameras/{camera_id}")
            assert delete_response.status_code == 409
            assert delete_response.json()["detail"] == impact
        finally:
            _cleanup_camera(client, camera_id)
