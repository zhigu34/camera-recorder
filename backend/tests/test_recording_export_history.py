import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.recording_export import ExportJob


def _create_camera(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/cameras",
        json={
            "name": name,
            "ip": "192.0.2.88",
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


async def _insert_job(camera_id: int, start: datetime, status: str = "ready") -> int:
    end = start + timedelta(minutes=5)
    async with SessionLocal() as session:
        job = ExportJob(
            camera_id=camera_id,
            requested_start_at=start,
            requested_end_at=end,
            export_mode="fast",
            gap_policy="merge",
            package_mode="individual",
            status=status,
            progress=100.0 if status == "ready" else 0.0,
            gap_count=0,
            requested_duration=300.0,
            covered_duration=300.0,
            completed_at=start + timedelta(minutes=1) if status == "ready" else None,
            expires_at=start + timedelta(hours=24) if status == "ready" else None,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return int(job.id)


def test_export_history_filters_camera_and_returns_newest_first():
    with TestClient(app) as client:
        camera_a = _create_camera(client, "export-history-a")
        camera_b = _create_camera(client, "export-history-b")
        base = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
        first = asyncio.run(_insert_job(camera_a, base))
        second = asyncio.run(_insert_job(camera_a, base + timedelta(hours=1), status="failed"))
        asyncio.run(_insert_job(camera_b, base + timedelta(hours=2)))

        response = client.get("/api/exports", params={"camera_id": camera_a, "limit": 10})

        assert response.status_code == 200, response.text
        body = response.json()
        assert [item["id"] for item in body] == [second, first]
        assert all(item["camera_id"] == camera_a for item in body)
        assert body[0]["status"] == "failed"


def test_export_history_respects_limit():
    with TestClient(app) as client:
        camera_id = _create_camera(client, "export-history-limit")
        base = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
        ids = [asyncio.run(_insert_job(camera_id, base + timedelta(minutes=index))) for index in range(3)]

        response = client.get("/api/exports", params={"camera_id": camera_id, "limit": 2})

        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()] == list(reversed(ids[-2:]))
