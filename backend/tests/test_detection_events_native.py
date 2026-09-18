import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.detection_event import DetectionEvent
from app.models.motion import MotionEvent


async def _insert_events(camera_id: int):
    base = datetime(2026, 9, 18, 7, 0, tzinfo=timezone.utc)
    async with SessionLocal() as db:
        motion = MotionEvent(
            camera_id=camera_id,
            started_at=base,
            ended_at=base + timedelta(seconds=2),
            peak_score=0.6,
        )
        native = DetectionEvent(
            camera_id=camera_id,
            source_kind="camera_native",
            provider="onvif",
            event_type="person",
            started_at=base + timedelta(seconds=5),
            ended_at=base + timedelta(seconds=5),
            metadata_json={"topic": "vendor:Analytics/People/PersonDetected"},
        )
        db.add_all([motion, native])
        await db.commit()
        await db.refresh(motion)
        await db.refresh(native)
        return motion.id, native.id, base


def _create_camera(client: TestClient) -> int:
    response = client.post(
        "/api/cameras",
        json={
            "name": "native-detection-events",
            "ip": "192.0.2.91",
            "username": "admin",
            "password": "secret",
            "rtsp_path": "/main",
            "enabled": False,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_detection_events_merge_legacy_and_camera_native_rows() -> None:
    with TestClient(app) as client:
        camera_id = _create_camera(client)
        motion_id, native_id, base = asyncio.run(_insert_events(camera_id))
        response = client.get(
            "/api/detection-events",
            params={
                "start": (base - timedelta(seconds=1)).isoformat(),
                "end": (base + timedelta(seconds=10)).isoformat(),
                "camera_id": camera_id,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert [(item["provider"], item["id"]) for item in body] == [
            ("onvif", native_id),
            ("motion", motion_id),
        ]
        assert body[0]["source_kind"] == "camera_native"
        assert body[0]["event_type"] == "person"
        assert body[0]["metadata"]["topic"].endswith("PersonDetected")


def test_detection_events_filter_camera_native_provider_and_type() -> None:
    with TestClient(app) as client:
        camera_id = _create_camera(client)
        _motion_id, native_id, base = asyncio.run(_insert_events(camera_id))
        response = client.get(
            "/api/detection-events",
            params={
                "start": (base - timedelta(seconds=1)).isoformat(),
                "end": (base + timedelta(seconds=10)).isoformat(),
                "camera_id": camera_id,
                "provider": "onvif",
                "event_type": "person",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [(item["provider"], item["id"]) for item in body] == [("onvif", native_id)]
