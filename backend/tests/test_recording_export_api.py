import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.recording import Recording
from app.models.recording_export import ExportArtifact, ExportJob
from app.services.recording_export import recording_export_manager


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


async def _insert_export_job(
    camera_id: int,
    start: datetime,
    end: datetime,
    *,
    status: str = "ready",
    expires_at: datetime | None = None,
) -> int:
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
            requested_duration=(end - start).total_seconds(),
            covered_duration=(end - start).total_seconds(),
            expires_at=expires_at,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return int(job.id)


async def _insert_artifact(job_id: int, path: Path) -> int:
    async with SessionLocal() as session:
        artifact = ExportArtifact(
            export_job_id=job_id,
            kind="mp4",
            segment_index=None,
            path=str(path),
            file_size=path.stat().st_size if path.exists() else 0,
        )
        session.add(artifact)
        await session.commit()
        await session.refresh(artifact)
        return int(artifact.id)


async def _mark_job_terminal(job_id: int) -> None:
    async with SessionLocal() as session:
        job = await session.get(ExportJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error_message = "test cleanup"
            await session.commit()


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


def test_export_analyze_rejects_unknown_camera():
    with TestClient(app) as client:
        start = datetime(2026, 9, 14, 11, 30, tzinfo=timezone.utc)
        response = client.post(
            "/api/exports/analyze",
            json={
                "camera_id": 999_999,
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(minutes=5)).isoformat(),
            },
        )
        assert response.status_code == 404


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


def test_export_create_rejects_range_without_local_coverage():
    with TestClient(app) as client:
        camera_id = _create_camera(client, "export-api-empty-camera")
        start = datetime(2026, 9, 14, 12, 30, tzinfo=timezone.utc)
        response = client.post(
            "/api/exports",
            json={
                "camera_id": camera_id,
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(minutes=5)).isoformat(),
            },
        )
        assert response.status_code == 409


def test_export_create_persists_job_and_enqueues_it(tmp_path, monkeypatch):
    with TestClient(app) as client:
        camera_id = _create_camera(client, "export-api-create-camera")
        start = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
        source = tmp_path / "ready.mp4"
        source.write_bytes(b"not-real-media-but-local")
        asyncio.run(_insert_recording(camera_id, source, start, start + timedelta(minutes=5)))
        queued: list[int] = []

        async def fake_enqueue(job_id: int) -> None:
            queued.append(job_id)

        monkeypatch.setattr(recording_export_manager, "enqueue", fake_enqueue)
        response = client.post(
            "/api/exports",
            json={
                "camera_id": camera_id,
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(minutes=5)).isoformat(),
                "export_mode": "fast",
                "gap_policy": "merge",
                "package_mode": "individual",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        job_id = int(body["id"])
        assert body["status"] == "pending"
        assert queued == [job_id]

        status_response = client.get(f"/api/exports/{job_id}")
        assert status_response.status_code == 200
        assert status_response.json()["camera_id"] == camera_id
        asyncio.run(_mark_job_terminal(job_id))


def test_export_download_enforces_artifact_job_ownership(tmp_path):
    with TestClient(app) as client:
        camera_id = _create_camera(client, "export-api-owner-camera")
        start = datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc)
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        owner_job = asyncio.run(_insert_export_job(camera_id, start, start + timedelta(minutes=5), expires_at=expires))
        other_job = asyncio.run(_insert_export_job(camera_id, start, start + timedelta(minutes=5), expires_at=expires))
        artifact_path = tmp_path / "owner.mp4"
        artifact_path.write_bytes(b"export")
        artifact_id = asyncio.run(_insert_artifact(owner_job, artifact_path))

        response = client.get(f"/api/exports/{other_job}/artifacts/{artifact_id}/download")
        assert response.status_code == 404


def test_export_download_rejects_expired_job(tmp_path):
    with TestClient(app) as client:
        camera_id = _create_camera(client, "export-api-expired-camera")
        start = datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)
        job_id = asyncio.run(
            _insert_export_job(
                camera_id,
                start,
                start + timedelta(minutes=5),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        artifact_path = tmp_path / "expired.mp4"
        artifact_path.write_bytes(b"export")
        artifact_id = asyncio.run(_insert_artifact(job_id, artifact_path))

        response = client.get(f"/api/exports/{job_id}/artifacts/{artifact_id}/download")
        assert response.status_code == 410


def test_export_download_rejects_path_outside_export_root(tmp_path):
    with TestClient(app) as client:
        camera_id = _create_camera(client, "export-api-containment-camera")
        start = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)
        job_id = asyncio.run(
            _insert_export_job(
                camera_id,
                start,
                start + timedelta(minutes=5),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"export")
        artifact_id = asyncio.run(_insert_artifact(job_id, outside))

        response = client.get(f"/api/exports/{job_id}/artifacts/{artifact_id}/download")
        assert response.status_code == 403
