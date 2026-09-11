from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all tables for metadata.create_all
from app.core.database import Base
from app.models.camera import Camera
from app.models.event import Event
from app.models.recording import Recording
from app.models.system_settings import SystemSettings
from app.services.storage_cleanup import StorageCleanupManager
import app.services.storage_cleanup as storage_cleanup_module


async def _database(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cleanup.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, Session


@pytest.mark.asyncio
async def test_emergency_cleanup_respects_disabled_retention(monkeypatch, tmp_path: Path):
    engine, Session = await _database(tmp_path)
    monkeypatch.setattr(storage_cleanup_module, "SessionLocal", Session)

    async with Session() as session:
        session.add(
            SystemSettings(
                id=1,
                storage_warning_percent=80,
                storage_critical_percent=90,
                local_retention_hours=-1,
            )
        )
        await session.commit()

    manager = StorageCleanupManager()
    monkeypatch.setattr(
        manager,
        "_usage",
        lambda: (SimpleNamespace(total=100, used=95, free=5), 95.0),
    )

    result = await manager.check_once()
    assert result["last_result"] == "disabled"
    assert result["deleted_files"] == 0

    async with Session() as session:
        event = await session.scalar(
            select(Event).where(Event.code == "storage.emergency_cleanup_blocked")
        )
        assert event is not None
        assert "自动清理已被禁用" in event.message

    await engine.dispose()


@pytest.mark.asyncio
async def test_emergency_cleanup_only_deletes_old_uploaded_recordings(
    monkeypatch, tmp_path: Path
):
    engine, Session = await _database(tmp_path)
    monkeypatch.setattr(storage_cleanup_module, "SessionLocal", Session)

    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    eligible_path = recordings_dir / "eligible.mp4"
    failed_path = recordings_dir / "failed.mp4"
    recent_path = recordings_dir / "recent.mp4"
    eligible_path.write_bytes(b"a" * 10)
    failed_path.write_bytes(b"b" * 10)
    recent_path.write_bytes(b"c" * 10)

    now = datetime.now(timezone.utc)
    async with Session() as session:
        session.add(
            SystemSettings(
                id=1,
                storage_warning_percent=80,
                storage_critical_percent=90,
                local_retention_hours=48,
            )
        )
        camera = Camera(
            name="cleanup-test",
            ip="127.0.0.1",
            username="admin",
            password_encrypted="encrypted",
        )
        session.add(camera)
        await session.flush()
        session.add_all(
            [
                Recording(
                    camera_id=camera.id,
                    mp4_path=str(eligible_path),
                    file_size=10,
                    status="ready",
                    upload_status="success",
                    ended_at=now - timedelta(hours=72),
                ),
                Recording(
                    camera_id=camera.id,
                    mp4_path=str(failed_path),
                    file_size=10,
                    status="ready",
                    upload_status="failed",
                    ended_at=now - timedelta(hours=72),
                ),
                Recording(
                    camera_id=camera.id,
                    mp4_path=str(recent_path),
                    file_size=10,
                    status="ready",
                    upload_status="success",
                    ended_at=now - timedelta(hours=1),
                ),
            ]
        )
        await session.commit()

    usage_values = iter(
        [
            (SimpleNamespace(total=100, used=95, free=5), 95.0),
            (SimpleNamespace(total=100, used=95, free=5), 95.0),
            (SimpleNamespace(total=100, used=79, free=21), 79.0),
        ]
    )
    manager = StorageCleanupManager()
    monkeypatch.setattr(manager, "_usage", lambda: next(usage_values))

    result = await manager.check_once()
    assert result["last_result"] == "completed"
    assert result["deleted_files"] == 1
    assert result["freed_bytes"] == 10
    assert not eligible_path.exists()
    assert failed_path.exists()
    assert recent_path.exists()

    async with Session() as session:
        rows = list(await session.scalars(select(Recording).order_by(Recording.id)))
        assert rows[0].status == "deleted"
        assert rows[1].status == "ready"
        assert rows[2].status == "ready"
        audit = await session.scalar(
            select(Event).where(Event.code == "storage.emergency_cleanup_completed")
        )
        assert audit is not None

    await engine.dispose()
