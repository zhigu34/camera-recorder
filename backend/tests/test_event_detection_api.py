import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.api import event_detection as detection_api
from app.core.database import SessionLocal
from app.main import app
from app.models.motion import MotionEvent


def _create_camera(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/cameras",
        json={
            "name": name,
            "ip": "192.0.2.61",
            "rtsp_port": 554,
            "username": "admin",
            "password": "secret",
            "rtsp_path": "/ch1/main",
            "sub_rtsp_path": "/ch1/sub",
            "enabled": True,
            "auto_record": False,
            "recording_schedule_enabled": False,
            "recording_schedule": [],
            "timestamp_mode": "reconstruct",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def _insert_motion_event(camera_id: int) -> tuple[int, datetime, datetime]:
    start = datetime.now(timezone.utc).replace(microsecond=0)
    end = start + timedelta(seconds=3)
    async with SessionLocal() as db:
        row = MotionEvent(
            camera_id=camera_id,
            started_at=start,
            ended_at=end,
            peak_score=0.78,
            metadata_json='{"detector":"motion-v2"}',
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return int(row.id), start, end


def test_event_detection_overview_is_honest_about_v1_capabilities() -> None:
    with TestClient(app) as client:
        camera_id = _create_camera(client, "event-detection-overview")
        response = client.get(f"/api/cameras/{camera_id}/event-detection")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["camera"]["id"] == camera_id
        assert [item["id"] for item in body["sources"]] == ["local.motion"]
        assert any(
            item["event_type"] == "person" and item["status"] == "unavailable"
            for item in body["capability_slots"]
        )
        assert all(item["source_id"] != "camera.onvif" for item in body["capability_slots"])


def test_unknown_event_source_detail_and_update_are_404() -> None:
    with TestClient(app) as client:
        camera_id = _create_camera(client, "event-detection-unknown")
        path = f"/api/cameras/{camera_id}/event-detection/sources/camera.onvif"
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["detail"] == "event source not found"
        response = client.put(path, json={"enabled": True})
        assert response.status_code == 404
        assert response.json()["detail"] == "event source not found"


def test_local_motion_source_update_uses_legacy_settings_contract(monkeypatch) -> None:
    async def no_restart(camera_id: int) -> None:
        return None

    monkeypatch.setattr(detection_api.motion_detection_manager, "restart_camera", no_restart)
    with TestClient(app) as client:
        camera_id = _create_camera(client, "event-detection-update")
        path = f"/api/cameras/{camera_id}/event-detection/sources/local.motion"
        response = client.put(
            path,
            json={
                "enabled": True,
                "sensitivity": "high",
                "analysis_fps": 4,
                "analysis_width": 640,
                "min_duration_ms": 900,
                "merge_gap_ms": 15000,
                "event_min_interval_ms": 120000,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["descriptor"]["id"] == "local.motion"
        assert body["config"]["enabled"] is True
        assert body["config"]["sensitivity"] == "high"


def test_detection_events_normalize_legacy_motion_without_relabeling() -> None:
    with TestClient(app) as client:
        camera_id = _create_camera(client, "event-detection-events")
        event_id, start, end = asyncio.run(_insert_motion_event(camera_id))
        query_start = (start - timedelta(seconds=1)).isoformat()
        query_end = (end + timedelta(seconds=1)).isoformat()
        response = client.get(
            "/api/detection-events",
            params={
                "start": query_start,
                "end": query_end,
                "camera_id": camera_id,
                "event_type": "motion",
                "provider": "motion",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [item["id"] for item in body] == [event_id]
        assert body[0]["source_kind"] == "local"
        assert body[0]["provider"] == "motion"
        assert body[0]["event_type"] == "motion"
        assert body[0]["confidence"] == 0.78
        assert body[0]["metadata"]["detector"] == "motion-v2"

        response = client.get(
            "/api/detection-events",
            params={
                "start": query_start,
                "end": query_end,
                "camera_id": camera_id,
                "event_type": "person",
            },
        )
        assert response.status_code == 200
        assert response.json() == []
