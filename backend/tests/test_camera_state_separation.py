from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.camera import Camera
from app.services.recording_schedule_manager import RecordingScheduleManager


def test_connectivity_recovers_from_legacy_overloaded_status() -> None:
    now = datetime.now(timezone.utc)
    camera = Camera(
        name="state-legacy",
        ip="192.0.2.10",
        password_encrypted="unused",
        status="scheduled",
        last_probe_at=now,
        last_online_at=now,
    )
    assert camera.connectivity_status == "online"

    camera.status = "stopped"
    camera.last_online_at = None
    assert camera.connectivity_status == "offline"


@pytest.mark.asyncio
async def test_schedule_reconcile_does_not_mutate_connectivity(monkeypatch) -> None:
    manager = RecordingScheduleManager()
    camera = SimpleNamespace(
        id=9001,
        enabled=True,
        auto_record=False,
        recording_schedule_enabled=False,
        recording_schedule=[],
        timestamp_mode="native",
        fps_num=None,
        fps_den=None,
        name="state-schedule",
        status="online",
    )

    monkeypatch.setattr(
        "app.services.recording_schedule_manager.recorder_manager.is_running",
        lambda camera_id: False,
    )

    await manager._reconcile_camera(
        camera,
        global_auto_start=True,
        now_local=datetime.now().astimezone(),
        session=SimpleNamespace(),
    )

    assert camera.status == "online"
    assert manager.state_for(camera) == "disabled"


def test_start_stop_preserve_probe_connectivity(monkeypatch) -> None:
    recorder_state = {"value": "STOPPED"}

    async def fake_probe_camera(**kwargs):
        return {
            "video_codec": "hevc",
            "video_profile": "Main",
            "width": 1920,
            "height": 1080,
            "fps_num": 15,
            "fps_den": 1,
            "fps": 15.0,
            "pixel_format": "yuv420p",
            "has_b_frames": 0,
            "video_time_base": "1/90000",
            "audio_codec": "aac",
            "audio_profile": "LC",
            "sample_rate": 16000,
            "channels": 1,
            "audio_frame_samples": 1024,
        }

    async def fake_start(config):
        recorder_state["value"] = "RECORDING"
        return {"camera_id": config.id, "state": "RECORDING", "pid": 123}

    async def fake_stop(camera_id):
        recorder_state["value"] = "STOPPED"
        return {"camera_id": camera_id, "state": "STOPPED", "pid": None}

    def fake_status(camera_id=None):
        if camera_id is None:
            return []
        return {"camera_id": camera_id, "state": recorder_state["value"], "pid": None}

    monkeypatch.setattr("app.api.cameras.probe_camera", fake_probe_camera)
    monkeypatch.setattr("app.services.recorder_manager.recorder_manager.start", fake_start)
    monkeypatch.setattr("app.services.recorder_manager.recorder_manager.stop", fake_stop)
    monkeypatch.setattr("app.services.recorder_manager.recorder_manager.status", fake_status)
    monkeypatch.setattr("app.services.recorder_manager.recorder_manager.is_running", lambda camera_id: False)

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json={
                "name": "pytest-state-separation",
                "ip": "192.0.2.111",
                "password": "test-secret",
                "rtsp_path": "/ch1/main",
                "timestamp_mode": "native",
                "auto_record": False,
            },
        )
        assert created.status_code == 201
        camera_id = created.json()["id"]

        probed = client.post(f"/api/cameras/{camera_id}/probe")
        assert probed.status_code == 200

        after_probe = client.get(f"/api/cameras/{camera_id}").json()
        assert after_probe["status"] == "online"
        assert after_probe["connectivity_status"] == "online"
        assert after_probe["recorder_state"] == "STOPPED"

        started = client.post(f"/api/cameras/{camera_id}/start")
        assert started.status_code == 200
        after_start = client.get(f"/api/cameras/{camera_id}").json()
        assert after_start["status"] == "online"
        assert after_start["connectivity_status"] == "online"
        assert after_start["recorder_state"] == "RECORDING"
        assert after_start["schedule_state"] == "manual_override"

        stopped = client.post(f"/api/cameras/{camera_id}/stop")
        assert stopped.status_code == 200
        after_stop = client.get(f"/api/cameras/{camera_id}").json()
        assert after_stop["status"] == "online"
        assert after_stop["connectivity_status"] == "online"
        assert after_stop["recorder_state"] == "STOPPED"
        assert after_stop["schedule_state"] == "manual_paused"

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204
