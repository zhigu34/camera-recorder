import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.services.recorder_manager as recorder_module
from app.core.database import Base, get_db
from app.main import app
from app.services.recorder_manager import CameraWorker


@pytest.fixture
def isolated_client(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'operations-release.db'}",
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
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        asyncio.run(engine.dispose())


def test_camera_log_rotation_is_bounded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(recorder_module, "CAMERA_LOG_MAX_BYTES", 32, raising=False)
    monkeypatch.setattr(recorder_module, "CAMERA_LOG_BACKUPS", 2, raising=False)
    path = tmp_path / "camera-1.log"

    for index in range(12):
        CameraWorker._append_log(path, f"line-{index:02d}-payload\n")

    assert path.stat().st_size <= 32
    assert (tmp_path / "camera-1.log.1").is_file()
    assert (tmp_path / "camera-1.log.2").is_file()
    assert not (tmp_path / "camera-1.log.3").exists()


def test_log_policy_is_visible(isolated_client) -> None:
    response = isolated_client.get("/api/operations/log-policy")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "camera_log_strategy": "size",
        "camera_log_max_bytes": 20 * 1024 * 1024,
        "camera_log_backups": 5,
        "deploy_log_strategy": "truncate_each_deploy",
    }


def test_high_value_configuration_mutations_are_audited(isolated_client) -> None:
    system_payload = {
        "app_name": "Audit Recorder",
        "segment_duration_seconds": 600,
        "remux_concurrency": 2,
        "rtsp_timeout_us": 5_000_000,
        "auto_start_enabled": True,
        "align_segments_to_clock": True,
        "storage_warning_percent": 80,
        "storage_critical_percent": 90,
        "upload_enabled": False,
        "upload_concurrency": 2,
        "upload_retry_max": 8,
        "webdav_url": "http://openlist:5244/dav",
        "webdav_root": "监控录像",
        "webdav_username": "admin",
        "local_retention_hours": 48,
    }
    assert isolated_client.put("/api/settings", json=system_payload).status_code == 200

    notification_payload = {
        "email_enabled": False,
        "offline_alert_seconds": 60,
        "recovery_stable_seconds": 10,
        "notify_recovery": True,
        "smtp_sender_name": "Camera Recorder",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_auth_enabled": False,
        "smtp_username": "",
        "smtp_from": "",
        "smtp_to": "",
        "recipients": [],
        "smtp_use_ssl": False,
        "smtp_starttls": True,
        "smtp_timeout_seconds": 15,
        "email_attach_images": False,
        "email_capture_interval_seconds": 2,
    }
    assert isolated_client.put("/api/notifications/email", json=notification_payload).status_code == 200

    created = isolated_client.post(
        "/api/cameras",
        json={
            "name": "Audit Camera",
            "ip": "192.0.2.77",
            "password": "test-secret",
            "timestamp_mode": "native",
        },
    )
    assert created.status_code == 201
    camera_id = created.json()["id"]

    assert isolated_client.put(
        f"/api/cameras/{camera_id}",
        json={"manufacturer": "Example", "model": "AuditCam"},
    ).status_code == 200
    assert isolated_client.delete(f"/api/cameras/{camera_id}").status_code == 204

    audit = isolated_client.get("/api/operations/audit", params={"limit": 50})
    assert audit.status_code == 200
    codes = {item["code"] for item in audit.json()}
    assert {
        "operations.system_settings_updated",
        "operations.notification_settings_updated",
        "operations.camera_created",
        "operations.camera_updated",
        "operations.camera_deleted",
    } <= codes
