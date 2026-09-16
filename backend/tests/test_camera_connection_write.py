import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.main import app
from app.models import Camera, CameraConnection


async def _connection_snapshot(camera_id: int) -> dict:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        assert camera is not None
        connection = camera.connection
        assert connection is not None
        assert connection.rtsp_config is not None
        connection_count = await db.scalar(
            select(func.count(CameraConnection.id)).where(CameraConnection.camera_id == camera_id)
        )
        return {
            "camera_id": camera.id,
            "connection_id": connection.id,
            "connection_count": int(connection_count or 0),
            "adapter": connection.adapter,
            "host": connection.host,
            "username": connection.username,
            "password_encrypted": connection.password_encrypted,
            "revision": connection.revision,
            "verification_status": connection.verification_status,
            "port": connection.rtsp_config.port,
            "main_path": connection.rtsp_config.main_path,
            "sub_path": connection.rtsp_config.sub_path,
            "legacy": {
                "connection_type": camera.connection_type,
                "ip": camera.ip,
                "rtsp_port": camera.rtsp_port,
                "username": camera.username,
                "password_encrypted": camera.password_encrypted,
                "rtsp_path": camera.rtsp_path,
                "sub_rtsp_path": camera.sub_rtsp_path,
            },
        }


def _create_payload(name: str) -> dict:
    return {
        "name": name,
        "ip": "192.0.2.30",
        "rtsp_port": 8554,
        "username": "operator",
        "password": "initial-secret",
        "rtsp_path": "/live/main",
        "sub_rtsp_path": "/live/sub",
        "timestamp_mode": "reconstruct",
    }


def test_manual_rtsp_create_persists_current_connection_and_legacy_shadow() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/cameras",
            json=_create_payload("pytest-current-connection-create"),
        )
        assert response.status_code == 201, response.text
        camera_id = int(response.json()["id"])

        snapshot = asyncio.run(_connection_snapshot(camera_id))
        assert snapshot["camera_id"] == camera_id
        assert snapshot["connection_count"] == 1
        assert snapshot["adapter"] == "manual_rtsp"
        assert snapshot["revision"] == 1
        assert snapshot["verification_status"] == "unverified"
        assert snapshot["host"] == "192.0.2.30"
        assert snapshot["port"] == 8554
        assert snapshot["username"] == "operator"
        assert decrypt_secret(snapshot["password_encrypted"]) == "initial-secret"
        assert snapshot["main_path"] == "/live/main"
        assert snapshot["sub_path"] == "/live/sub"
        assert snapshot["legacy"] == {
            "connection_type": "manual_rtsp",
            "ip": "192.0.2.30",
            "rtsp_port": 8554,
            "username": "operator",
            "password_encrypted": snapshot["password_encrypted"],
            "rtsp_path": "/live/main",
            "sub_rtsp_path": "/live/sub",
        }

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


def test_manual_rtsp_update_preserves_connection_id_and_revises_only_connection_changes() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json=_create_payload("pytest-current-connection-update"),
        )
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_connection_snapshot(camera_id))
        assert before["revision"] == 1

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "ip": "192.0.2.31",
                "rtsp_port": 9554,
                "username": "viewer",
                "password": "updated-secret",
                "rtsp_path": "/updated/main",
                "sub_rtsp_path": "/updated/sub",
            },
        )
        assert updated.status_code == 200, updated.text
        after = asyncio.run(_connection_snapshot(camera_id))

        assert after["camera_id"] == camera_id
        assert after["connection_id"] == before["connection_id"]
        assert after["connection_count"] == 1
        assert after["revision"] == 2
        assert after["host"] == "192.0.2.31"
        assert after["port"] == 9554
        assert after["username"] == "viewer"
        assert decrypt_secret(after["password_encrypted"]) == "updated-secret"
        assert after["main_path"] == "/updated/main"
        assert after["sub_path"] == "/updated/sub"
        assert after["legacy"] == {
            "connection_type": "manual_rtsp",
            "ip": "192.0.2.31",
            "rtsp_port": 9554,
            "username": "viewer",
            "password_encrypted": after["password_encrypted"],
            "rtsp_path": "/updated/main",
            "sub_rtsp_path": "/updated/sub",
        }

        metadata_only = client.put(
            f"/api/cameras/{camera_id}",
            json={"name": "pytest-current-connection-update-renamed", "enabled": False},
        )
        assert metadata_only.status_code == 200, metadata_only.text
        after_metadata = asyncio.run(_connection_snapshot(camera_id))
        assert after_metadata["connection_id"] == before["connection_id"]
        assert after_metadata["revision"] == 2

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204
