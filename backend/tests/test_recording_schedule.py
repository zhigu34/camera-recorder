from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.services.recording_schedule import recording_schedule_allows


def camera(*, enabled: bool = True, windows=None):
    return SimpleNamespace(
        recording_schedule_enabled=enabled,
        recording_schedule=windows or [],
    )


def local_time(hour: int, minute: int = 0) -> datetime:
    local_tz = datetime.now().astimezone().tzinfo
    return datetime(2026, 9, 11, hour, minute, tzinfo=local_tz)


def test_schedule_disabled_keeps_all_day_behavior() -> None:
    assert recording_schedule_allows(camera(enabled=False), local_time(3, 12)) is True


def test_schedule_matches_normal_and_cross_midnight_windows() -> None:
    daytime = camera(windows=[{"start": "08:00", "end": "18:00"}])
    assert recording_schedule_allows(daytime, local_time(9, 0)) is True
    assert recording_schedule_allows(daytime, local_time(20, 0)) is False

    overnight = camera(windows=[{"start": "22:00", "end": "06:00"}])
    assert recording_schedule_allows(overnight, local_time(23, 30)) is True
    assert recording_schedule_allows(overnight, local_time(2, 0)) is True
    assert recording_schedule_allows(overnight, local_time(12, 0)) is False


def test_enabled_schedule_without_windows_records_nothing() -> None:
    assert recording_schedule_allows(camera(enabled=True, windows=[]), local_time(12, 0)) is False


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
            {"start": "08:00", "end": "12:00"},
            {"start": "22:00", "end": "06:00"},
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
                "recording_schedule": [{"start": "18:30", "end": "23:45"}],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["recording_schedule"] == [
            {"start": "18:30", "end": "23:45"}
        ]

        invalid = client.put(
            f"/api/cameras/{camera_id}",
            json={"recording_schedule_enabled": True, "recording_schedule": []},
        )
        assert invalid.status_code == 422

        response = client.delete(f"/api/cameras/{camera_id}")
        assert response.status_code == 204
