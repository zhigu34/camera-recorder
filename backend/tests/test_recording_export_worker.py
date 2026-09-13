import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import app
from app.models.recording import Recording
from app.models.recording_export import ExportArtifact, ExportJob
from app.services import recording_export as exports


def _create_camera(name: str) -> int:
    with TestClient(app) as client:
        response = client.post(
            "/api/cameras",
            json={
                "name": name,
                "ip": "192.0.2.89",
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


async def _insert_job(
    camera_id: int,
    start: datetime,
    end: datetime,
    *,
    status: str = "pending",
    gap_policy: str = "merge",
    package_mode: str = "individual",
    expires_at: datetime | None = None,
) -> int:
    async with SessionLocal() as session:
        job = ExportJob(
            camera_id=camera_id,
            requested_start_at=start,
            requested_end_at=end,
            export_mode="fast",
            gap_policy=gap_policy,
            package_mode=package_mode,
            status=status,
            progress=0,
            gap_count=0,
            requested_duration=(end - start).total_seconds(),
            covered_duration=0,
            expires_at=expires_at,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return int(job.id)


async def _insert_recording(
    camera_id: int,
    path: Path,
    start: datetime,
    end: datetime,
) -> int:
    async with SessionLocal() as session:
        recording = Recording(
            camera_id=camera_id,
            started_at=start,
            ended_at=end,
            duration=(end - start).total_seconds(),
            mp4_path=str(path),
            file_size=path.stat().st_size,
            video_codec="h264",
            audio_codec="aac",
            status="ready",
        )
        session.add(recording)
        await session.commit()
        await session.refresh(recording)
        return int(recording.id)


def test_recover_marks_processing_failed_and_requeues_pending():
    camera_id = _create_camera("export-worker-recovery-camera")
    start = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
    processing_id = asyncio.run(
        _insert_job(camera_id, start, start + timedelta(minutes=5), status="processing")
    )
    pending_id = asyncio.run(
        _insert_job(camera_id, start, start + timedelta(minutes=5), status="pending")
    )
    manager = exports.RecordingExportManager()

    asyncio.run(manager._recover_jobs())

    async def inspect():
        async with SessionLocal() as session:
            processing = await session.get(ExportJob, processing_id)
            pending = await session.get(ExportJob, pending_id)
            return processing, pending

    processing, pending = asyncio.run(inspect())
    assert processing is not None
    assert processing.status == "failed"
    assert "restart" in (processing.error_message or "").lower()
    assert pending is not None and pending.status == "pending"
    assert pending_id in manager._queued
    assert manager._queue.qsize() == 1


def test_split_zip_job_creates_stored_bundle_and_preserves_sources(tmp_path, monkeypatch):
    camera_id = _create_camera("export-worker-zip-camera")
    start = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)
    first = tmp_path / "source-first.mp4"
    second = tmp_path / "source-second.mp4"
    first_bytes = b"original-first"
    second_bytes = b"original-second"
    first.write_bytes(first_bytes)
    second.write_bytes(second_bytes)
    asyncio.run(_insert_recording(camera_id, first, start, start + timedelta(minutes=5)))
    asyncio.run(
        _insert_recording(
            camera_id,
            second,
            start + timedelta(minutes=6),
            start + timedelta(minutes=10),
        )
    )
    job_id = asyncio.run(
        _insert_job(
            camera_id,
            start,
            start + timedelta(minutes=10),
            gap_policy="split",
            package_mode="zip",
        )
    )
    root = tmp_path / "exports"
    monkeypatch.setattr(exports, "export_root", lambda: root)
    manager = exports.RecordingExportManager()

    async def fake_render(job, group, work_dir, index):
        path = work_dir / f"group-{index:03d}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"group-{index}".encode())
        return path

    monkeypatch.setattr(manager, "_render_group", fake_render)
    asyncio.run(manager.process_job(job_id))

    async def inspect():
        async with SessionLocal() as session:
            job = await session.get(ExportJob, job_id)
            artifacts = list(
                await session.scalars(
                    select(ExportArtifact).where(ExportArtifact.export_job_id == job_id)
                )
            )
            return job, artifacts

    job, artifacts = asyncio.run(inspect())
    assert job is not None and job.status == "ready"
    assert job.progress == 100.0
    assert job.gap_count == 1
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.kind == "zip"
    bundle = Path(artifact.path)
    assert bundle.is_file()
    with ZipFile(bundle) as archive:
        assert all(info.compress_type == ZIP_STORED for info in archive.infolist())
        manifest = json.loads(archive.read("export-info.json"))
        assert manifest["gap_policy"] == "split"
        assert len(manifest["files"]) == 2
        assert len(manifest["gaps"]) == 1
    assert first.read_bytes() == first_bytes
    assert second.read_bytes() == second_bytes


def test_expiry_cleanup_only_removes_export_directory(tmp_path, monkeypatch):
    camera_id = _create_camera("export-worker-expiry-camera")
    start = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-must-survive")
    asyncio.run(_insert_recording(camera_id, source, start, start + timedelta(minutes=5)))
    job_id = asyncio.run(
        _insert_job(
            camera_id,
            start,
            start + timedelta(minutes=5),
            status="ready",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    root = tmp_path / "exports"
    monkeypatch.setattr(exports, "export_root", lambda: root)

    async def prepare_directory():
        async with SessionLocal() as session:
            job = await session.get(ExportJob, job_id)
            assert job is not None
            directory = exports.job_directory(job)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "artifact.mp4").write_bytes(b"export")
            return directory

    directory = asyncio.run(prepare_directory())
    manager = exports.RecordingExportManager()
    asyncio.run(manager.cleanup_expired())

    async def status_of_job():
        async with SessionLocal() as session:
            job = await session.get(ExportJob, job_id)
            return job.status if job is not None else None

    assert asyncio.run(status_of_job()) == "expired"
    assert not directory.exists()
    assert source.read_bytes() == b"source-must-survive"
