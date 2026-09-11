from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.camera import CameraRead
from app.services.recording_schedule import recording_schedule_allows
from app.services.recording_schedule_manager import recording_schedule_manager


def camera(*, enabled: bool = True, windows=None):
    return SimpleNamespace(
        recording_schedule_enabled=enabled,
        recording_schedule=windows or [],
    )


def local_time(day: int, hour: int, minute: int = 0) -> datetime:
    local_tz = datetime.now().astimezone().tzinfo
    return datetime(2026, 9, day, hour, minute, tzinfo=local_tz)


def test_schedule_disabled_keeps_all_day_behavior() -> None:
    assert recording_schedule_allows(camera(enabled=False), local_time(11, 3, 12)) is True


def test_legacy_schedule_without_days_still_runs_every_day() -> None:
    legacy = camera(windows=[{"start": "08:00", "end": "18:00"}])
    assert recording_schedule_allows(legacy, local_time(11, 9, 0)) is True
    assert recording_schedule_allows(legacy, local_time(13, 9, 0)) is True


def test_weekly_schedule_and_cross_midnight_use_start_day() -> None:
    weekdays = camera(
        windows=[{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00"}]
    )
    # 2026-09-11 is Friday; 2026-09-12 is Saturday.
    assert recording_schedule_allows(weekdays, local_time(11, 9, 0)) is True
    assert recording_schedule_allows(weekdays, local_time(12, 9, 0)) is False

    friday_overnight = camera(
        windows=[{"days": [4], "start": "22:00", "end": "06:00"}]
    )
    assert recording_schedule_allows(friday_overnight, local_time(11, 23, 30)) is True
    assert recording_schedule_allows(friday_overnight, local_time(12, 2, 0)) is True
    assert recording_schedule_allows(friday_overnight, local_time(12, 23, 0)) is False


def test_enabled_schedule_without_windows_records_nothing() -> None:
    assert recording_schedule_allows(camera(enabled=True, windows=[]), local_time(11, 12, 0)) is False


def test_camera_read_tolerates_incomplete_legacy_schedule() -> None:
    now = datetime.now().astimezone()
    result = CameraRead.model_validate(
        {
            "id": 1,
            "name": "legacy-camera",
            "ip": "192.0.2.70",
            "rtsp_port": 554,
            "username": "admin",
            "rtsp_path": "/ch1/main",
            "enabled": True,
            "auto_record": True,
            "recording_schedule_enabled": True,
            "recording_schedule": None,
            "timestamp_mode": "native",
            "status": "unknown",
            "connectivity_status": "unknown",
            "created_at": now,
            "updated_at": now,
        }
    )
    assert result.recording_schedule_enabled is True
    assert result.recording_schedule == []


def test_camera_schedule_create_update_and_read() -> None:
    payload = {
        "name": "pytest-scheduled-camera",
        "ip": "192.0.2.88",
        "username": "admin",
        "password": "test-secret",
        "rtsp_path": "/ch1/main",
        "timestamp_mode": "native",
        "enabled": True,
        "auto_record": False,
        "recording_schedule_enabled": True,
        "recording_schedule": [
            {"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "12:00"},
            {"days": [4], "start": "22:00", "end": "06:00"},
        ],
    }

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=payload)
        assert created.status_code == 201
        camera_id = created.json()["id"]
        assert created.json()["recording_schedule_enabled"] is True
        assert created.json()["recording_schedule"] == payload["recording_schedule"]

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "recording_schedule_enabled": True,
                "recording_schedule": [
                    {"days": [5, 6], "start": "18:30", "end": "23:45"}
                ],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["recording_schedule"] == [
            {"days": [5, 6], "start": "18:30", "end": "23:45"}
        ]

        invalid = client.put(
            f"/api/cameras/{camera_id}",
            json={"recording_schedule_enabled": True, "recording_schedule": []},
        )
        assert invalid.status_code == 422

        response = client.delete(f"/api/cameras/{camera_id}")
        assert response.status_code == 204


def test_schedule_update_survives_runtime_reconcile_failure(monkeypatch) -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json={
                "name": "pytest-schedule-runtime-failure",
                "ip": "192.0.2.89",
                "password": "test-secret",
                "timestamp_mode": "native",
                "auto_record": False,
            },
        )
        assert created.status_code == 201
        camera_id = created.json()["id"]

        async def broken_reconcile_camera(*args, **kwargs):
            raise RuntimeError("simulated camera reconcile failure")

        monkeypatch.setattr(
            recording_schedule_manager,
            "_reconcile_camera",
            broken_reconcile_camera,
        )
        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "auto_record": True,
                "recording_schedule_enabled": True,
                "recording_schedule": [
                    {"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00"}
                ],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["recording_schedule_enabled"] is True
        assert updated.json()["recording_schedule"][0]["start"] == "08:00"
        assert recording_schedule_manager.status()["last_error"] is not None

        response = client.delete(f"/api/cameras/{camera_id}")
        assert response.status_code == 204


def test_batch_apply_weekly_schedule() -> None:
    camera_ids: list[int] = []
    with TestClient(app) as client:
        for suffix in ("a", "b"):
            created = client.post(
                "/api/cameras",
                json={
                    "name": f"pytest-schedule-batch-{suffix}",
                    "ip": f"192.0.2.{90 if suffix == 'a' else 91}",
                    "password": "test-secret",
                    "timestamp_mode": "native",
                    "auto_record": False,
                },
            )
            assert created.status_code == 201
            camera_ids.append(created.json()["id"])

        payload = {
            "camera_ids": camera_ids,
            "auto_record": False,
            "recording_schedule_enabled": True,
            "recording_schedule": [
                {"days": [0, 1, 2, 3, 4], "start": "07:30", "end": "19:00"},
                {"days": [5, 6], "start": "09:00", "end": "12:00"},
            ],
        }
        applied = client.put("/api/cameras/recording-schedule/batch", json=payload)
        assert applied.status_code == 200
        assert applied.json()["updated"] == 2
        assert sorted(applied.json()["camera_ids"]) == sorted(camera_ids)

        for camera_id in camera_ids:
            result = client.get(f"/api/cameras/{camera_id}")
            assert result.status_code == 200
            assert result.json()["recording_schedule"] == payload["recording_schedule"]
            client.delete(f"/api/cameras/{camera_id}")
