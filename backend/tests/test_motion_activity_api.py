import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.motion import MotionEvent


def _create_camera(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/cameras",
        json={
            "name": name,
            "ip": "192.0.2.81",
            "rtsp_port": 554,
            "username": "admin",
            "password": "secret",
            "rtsp_path": "/ch1/main",
            "enabled": True,
            "auto_record": False,
            "recording_schedule_enabled": False,
            "recording_schedule": [],
            "timestamp_mode": "reconstruct",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def _insert_events(camera_id: int) -> list[int]:
    base = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    ids: list[int] = []
    async with SessionLocal() as db:
        for offset in range(3):
            started_at = base + timedelta(minutes=offset)
            row = MotionEvent(
                camera_id=camera_id,
                started_at=started_at,
                ended_at=started_at + timedelta(seconds=3),
                peak_score=0.5 + offset / 10,
            )
            db.add(row)
            await db.flush()
            ids.append(int(row.id))
        await db.commit()
    return ids


def test_motion_events_allow_cross_camera_query() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/motion-events",
            params={
                "start": "2026-09-14T00:00:00",
                "end": "2026-09-14T23:59:59.999999",
                "limit": 10,
            },
        )

        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)


def test_motion_events_limit_returns_latest_rows_first() -> None:
    with TestClient(app) as client:
        camera_id = _create_camera(client, "motion-activity-latest")
        ids = asyncio.run(_insert_events(camera_id))

        response = client.get(
            "/api/motion-events",
            params={
                "start": "2026-09-14T00:00:00+00:00",
                "end": "2026-09-14T23:59:59.999999+00:00",
                "camera_id": camera_id,
                "limit": 2,
            },
        )

        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()] == [ids[2], ids[1]]
