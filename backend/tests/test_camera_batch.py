import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.main import app
from app.models import Camera, CameraConnection


async def _batch_connection_snapshot(camera_id: int) -> dict:
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
            "adapter": connection.adapter,
            "revision": connection.revision,
            "count": int(connection_count or 0),
            "host": connection.host,
            "port": connection.rtsp_config.port,
            "main_path": connection.rtsp_config.main_path,
            "sub_path": connection.rtsp_config.sub_path,
        }


def test_batch_camera_create_and_skip_existing() -> None:
    payload = {
        "skip_existing": True,
        "cameras": [
            {
                "name": "pytest-batch-camera-a",
                "ip": "192.0.2.10",
                "username": "admin",
                "password": "test-secret-a",
                "rtsp_path": "/ch1/main",
                "sub_rtsp_path": "/ch1/sub",
                "timestamp_mode": "reconstruct",
            },
            {
                "name": "pytest-batch-camera-b",
                "ip": "192.0.2.11",
                "username": "admin",
                "password": "test-secret-b",
                "rtsp_path": "/ch1/main",
                "timestamp_mode": "native",
            },
        ],
    }

    with TestClient(app) as client:
        first = client.post("/api/cameras/batch", json=payload)
        assert first.status_code == 201
        first_body = first.json()
        assert first_body["created"] == 2
        assert first_body["skipped"] == 0

        created_camera = client.get(f"/api/cameras/{first_body['created_ids'][0]}")
        assert created_camera.status_code == 200
        assert created_camera.json()["sub_rtsp_path"] == "/ch1/sub"

        first_connection = asyncio.run(_batch_connection_snapshot(first_body["created_ids"][0]))
        second_connection = asyncio.run(_batch_connection_snapshot(first_body["created_ids"][1]))
        assert first_connection == {
            "adapter": "manual_rtsp",
            "revision": 1,
            "count": 1,
            "host": "192.0.2.10",
            "port": 554,
            "main_path": "/ch1/main",
            "sub_path": "/ch1/sub",
        }
        assert second_connection == {
            "adapter": "manual_rtsp",
            "revision": 1,
            "count": 1,
            "host": "192.0.2.11",
            "port": 554,
            "main_path": "/ch1/main",
            "sub_path": None,
        }

        second = client.post("/api/cameras/batch", json=payload)
        assert second.status_code == 201
        second_body = second.json()
        assert second_body["created"] == 0
        assert second_body["skipped"] == 2
        assert second_body["skipped_names"] == [
            "pytest-batch-camera-a",
            "pytest-batch-camera-b",
        ]

        for camera_id in first_body["created_ids"]:
            response = client.delete(f"/api/cameras/{camera_id}")
            assert response.status_code == 204


def test_batch_camera_rejects_duplicate_names_in_same_request() -> None:
    payload = {
        "skip_existing": True,
        "cameras": [
            {
                "name": "pytest-duplicate-camera",
                "ip": "192.0.2.20",
                "password": "test-secret-a",
            },
            {
                "name": "pytest-duplicate-camera",
                "ip": "192.0.2.21",
                "password": "test-secret-b",
            },
        ],
    }

    with TestClient(app) as client:
        response = client.post("/api/cameras/batch", json=payload)

    assert response.status_code == 422
    assert "重复名称" in response.json()["detail"]
