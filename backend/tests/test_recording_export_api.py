import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.recording import Recording


def _create_camera(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/cameras",
        json={
            "name": name,
            "ip": "192.0.2.77",
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


async def _insert_recording(camera_id: int, path: Path, start: datetime, end: datetime) -> int:
    async with SessionLocal() as session:
        item = Recording(
            camera_id=camera_id,
            started_at=start,
            ended_at=end,
            duration=(end - start).total_seconds(),
            mp4_path=str(path),
            file_size=path.stat().st_size if path.exists() else 0,
            video_codec="h264",
            audio_codec="aac",
            status="ready",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return int(item.id)


def test_export_analyze_reports_local_coverage_and_gap(tmp_path):
    with TestClient(app) as client:
        camera_id = _create_camera(client, "export-api-analyze-camera")
        start = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
        first = tmp_path / "first.mp4"
        third = tmp_path / "third.mp4"
        first.write_bytes(b"mp4-a")
        third.write_bytes(b"mp4-c")
        asyncio.run(_insert_recording(camera_id, first, start, start + timedelta(minutes=5)))
        asyncio.run(
            _insert_recording(
                camera_id,
                third,
                start + timedelta(minutes=10),
                start + timedelta(minutes=15),
            )
        )

        response = client.post(
            "/api/exports/analyze",
            json={
                "camera_id": camera_id,
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(minutes=15)).isoformat(),
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["exportable"] is True
        assert body["recording_count"] == 2
        assert len(body["continuous_groups"]) == 2
        assert len(body["gaps"]) == 1
        assert body["gaps"][0]["duration"] == 300.0


def test_export_analyze_treats_missing_local_file_as_unavailable(tmp_path):
    with TestClient(app) as client:
        camera_id = _create_camera(client, "export-api-missing-camera")
        start = datetime(2026, 9, 14, 11, 0, tzinfo=timezone.utc)
        missing = tmp_path / "already-cleaned.mp4"
        asyncio.run(_insert_recording(camera_id, missing, start, start + timedelta(minutes=5)))

        response = client.post(
            "/api/exports/analyze",
            json={
                "camera_id": camera_id,
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(minutes=5)).isoformat(),
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["exportable"] is False
        assert body["unavailable_count"] == 1
        assert len(body["unavailable_intervals"]) == 1


def test_export_create_rejects_zip_for_merge_before_enqueuing():
    with TestClient(app) as client:
        start = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
        response = client.post(
            "/api/exports",
            json={
                "camera_id": 1,
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(minutes=1)).isoformat(),
                "gap_policy": "merge",
                "package_mode": "zip",
            },
        )
        assert response.status_code == 422


def test_export_create_rejects_range_over_24_hours():
    with TestClient(app) as client:
        start = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
        response = client.post(
            "/api/exports",
            json={
                "camera_id": 1,
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(hours=24, seconds=1)).isoformat(),
            },
        )
        assert response.status_code == 422
