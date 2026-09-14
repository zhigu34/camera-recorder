import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.camera import Camera
from app.models.notification_settings import NotificationSettings
from app.models.system_settings import SystemSettings


@pytest.fixture
def isolated_session(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'operations.db'}",
        poolclass=NullPool,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        yield Session
    finally:
        app.dependency_overrides.pop(get_db, None)
        asyncio.run(engine.dispose())


def test_operations_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/operations/logs" in paths
    assert "/api/operations/backup" in paths
    assert "/api/operations/restore" in paths
    assert "/api/operations/audit" in paths
    assert "/metrics" in paths


def test_log_listing_is_scoped_to_configured_logs_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "logs_dir", tmp_path)
    (tmp_path / "camera-1.log").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "worker.log").write_text("worker\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "hidden.log").write_text("hidden\n", encoding="utf-8")

    client = TestClient(app)
    response = client.get("/api/operations/logs")

    assert response.status_code == 200
    payload = response.json()
    assert [item["name"] for item in payload] == ["camera-1.log", "worker.log"]
    assert all(item["size_bytes"] > 0 for item in payload)


def test_log_view_is_bounded_and_downloads_only_direct_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "logs_dir", tmp_path)
    (tmp_path / "camera-1.log").write_text("one\ntwo\nthree\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.log"
    outside.write_text("secret\n", encoding="utf-8")

    client = TestClient(app)
    viewed = client.get("/api/operations/logs/camera-1.log", params={"tail_lines": 2})
    downloaded = client.get("/api/operations/logs/camera-1.log/download")
    traversal = client.get("/api/operations/logs/%2E%2E%2Foutside.log")

    assert viewed.status_code == 200
    assert viewed.json()["content"] == "two\nthree\n"
    assert downloaded.status_code == 200
    assert downloaded.content == b"one\ntwo\nthree\n"
    assert traversal.status_code in {400, 404}
    assert b"secret" not in traversal.content


def test_backup_is_secret_free_and_restore_preserves_existing_secrets(
    isolated_session,
) -> None:
    Session = isolated_session

    async def seed() -> None:
        async with Session() as session:
            session.add(
                SystemSettings(
                    id=1,
                    app_name="Before",
                    webdav_username="archive-user",
                    webdav_password_encrypted="WEB-DAV-CIPHER",
                )
            )
            session.add(
                NotificationSettings(
                    id=1,
                    email_enabled=True,
                    smtp_host="smtp.example.test",
                    smtp_username="mail-user",
                    smtp_password_encrypted="SMTP-CIPHER",
                )
            )
            session.add(
                Camera(
                    id=1,
                    name="Front Door",
                    ip="192.0.2.21",
                    username="camera-user",
                    password_encrypted="CAMERA-CIPHER",
                    rtsp_path="/main",
                )
            )
            await session.commit()

    asyncio.run(seed())
    client = TestClient(app)

    exported = client.get("/api/operations/backup")
    assert exported.status_code == 200
    backup = exported.json()
    encoded = json.dumps(backup, ensure_ascii=False)
    assert backup["version"] == 1
    assert "WEB-DAV-CIPHER" not in encoded
    assert "SMTP-CIPHER" not in encoded
    assert "CAMERA-CIPHER" not in encoded
    assert "webdav_password_encrypted" not in encoded
    assert "smtp_password_encrypted" not in encoded
    assert "password_encrypted" not in encoded

    backup["system"]["app_name"] = "Restored"
    backup["notifications"]["smtp_host"] = "smtp.restored.test"
    backup["cameras"][0]["ip"] = "192.0.2.99"
    backup["cameras"].append(
        {
            "name": "Missing Camera",
            "ip": "192.0.2.50",
            "rtsp_port": 554,
            "username": "admin",
            "rtsp_path": "/main",
            "sub_rtsp_path": None,
            "manufacturer": None,
            "model": None,
            "form_factor": "unknown",
            "enabled": True,
            "auto_record": False,
            "recording_schedule_enabled": False,
            "recording_schedule": [],
            "timestamp_mode": "reconstruct",
        }
    )

    restored = client.post("/api/operations/restore", json=backup)
    assert restored.status_code == 200
    assert restored.json()["restored_cameras"] == 1
    assert restored.json()["skipped_cameras"] == ["Missing Camera"]

    async def verify() -> None:
        async with Session() as session:
            system = await session.get(SystemSettings, 1)
            notifications = await session.get(NotificationSettings, 1)
            camera = await session.get(Camera, 1)
            assert system is not None
            assert notifications is not None
            assert camera is not None
            assert system.app_name == "Restored"
            assert system.webdav_password_encrypted == "WEB-DAV-CIPHER"
            assert notifications.smtp_host == "smtp.restored.test"
            assert notifications.smtp_password_encrypted == "SMTP-CIPHER"
            assert camera.ip == "192.0.2.99"
            assert camera.password_encrypted == "CAMERA-CIPHER"

    asyncio.run(verify())


def test_audit_and_prometheus_metrics_are_exposed(isolated_session, tmp_path, monkeypatch) -> None:
    Session = isolated_session
    monkeypatch.setattr(settings, "recordings_dir", tmp_path)

    async def seed() -> None:
        async with Session() as session:
            session.add(SystemSettings(id=1))
            session.add(
                Camera(
                    id=1,
                    name="Metrics Camera",
                    ip="192.0.2.31",
                    password_encrypted="secret",
                    status="online",
                )
            )
            await session.commit()

    asyncio.run(seed())
    client = TestClient(app)
    exported = client.get("/api/operations/backup")
    assert exported.status_code == 200

    audit = client.get("/api/operations/audit", params={"limit": 20})
    assert audit.status_code == 200
    assert any(item["code"] == "operations.backup_exported" for item in audit.json())

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    body = metrics.text
    assert "camera_recorder_cameras_total" in body
    assert "camera_recorder_cameras_online" in body
    assert "camera_recorder_recorders_running" in body
    assert "camera_recorder_connectivity_monitor_errors_total" in body
    assert "camera_recorder_storage_used_bytes" in body
