import asyncio

from fastapi.testclient import TestClient

from app.api import hik_cameras as hik_api
from app.core.database import SessionLocal
from app.main import app
from app.models.hikvision import HikDeviceMetadata
from app.schemas.hikvision import HikProbeResult


DISCOVERED = HikProbeResult(
    serial_number="HIK-SN-42",
    device_type=42,
    device_model="DS-2CD-Test",
    device_name="Front Gate",
    start_channel=1,
    analog_channel_count=1,
    digital_channel_count=0,
    channel=1,
)


def _media_probe_result() -> dict:
    return {
        "ok": True,
        "video_codec": "h264",
        "video_profile": "High",
        "width": 1920,
        "height": 1080,
        "fps_num": 25,
        "fps_den": 1,
        "fps": 25.0,
        "pixel_format": "yuv420p",
        "has_b_frames": 0,
        "video_time_base": "1/90000",
        "audio_codec": "aac",
        "audio_profile": "LC",
        "sample_rate": 48000,
        "channels": 1,
        "audio_frame_samples": 1024,
    }


async def _metadata(camera_id: int) -> HikDeviceMetadata | None:
    async with SessionLocal() as db:
        return await db.get(HikDeviceMetadata, camera_id)


def test_hik_camera_creation_reprobes_media_and_persists_adapter_metadata(monkeypatch) -> None:
    probe_calls = 0
    media_calls = 0

    async def fake_probe(_payload):
        nonlocal probe_calls
        probe_calls += 1
        return DISCOVERED

    async def fake_validate(_payload, _db):
        nonlocal media_calls
        media_calls += 1
        return _media_probe_result()

    async def no_reconcile():
        return None

    monkeypatch.setattr(hik_api, "_probe_hik", fake_probe)
    monkeypatch.setattr(hik_api, "_validate_main_stream", fake_validate)
    monkeypatch.setattr(hik_api.recording_schedule_manager, "reconcile", no_reconcile)

    with TestClient(app) as client:
        response = client.post(
            "/api/cameras/hik",
            json={
                "name": "hik-api-camera",
                "host": "10.0.0.80",
                "port": 8000,
                "username": "admin",
                "password": "private-secret",
                "channel": 2,
                "enabled": True,
                "auto_record": False,
                "timestamp_mode": "reconstruct",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        camera_id = int(body["id"])
        assert body["connection_type"] == "hik_sdk"
        assert body["manufacturer"] == "Hikvision"
        assert body["model"] == "DS-2CD-Test"
        assert body["video_codec"] == "h264"
        assert "private-secret" not in response.text
        assert probe_calls == 1
        assert media_calls == 1

        metadata = asyncio.run(_metadata(camera_id))
        assert metadata is not None
        assert metadata.sdk_port == 8000
        assert metadata.channel == 2
        assert metadata.main_stream_type == 0
        assert metadata.sub_stream_type == 1
        assert metadata.device_serial == "HIK-SN-42"


def test_hik_same_adapter_update_uses_runtime_coordinator(monkeypatch) -> None:
    coordinator_calls: list[tuple[int, bool]] = []
    legacy_calls: list[tuple[str, int]] = []

    async def fake_probe(_payload):
        return DISCOVERED

    async def fake_validate(_payload, _db):
        return _media_probe_result()

    async def no_reconcile():
        return None

    class Coordinator:
        async def reload(self, camera_id: int, *, schedule_changed: bool = False) -> str:
            coordinator_calls.append((camera_id, schedule_changed))
            return "running"

    monkeypatch.setattr(hik_api, "_probe_hik", fake_probe)
    monkeypatch.setattr(hik_api, "_validate_main_stream", fake_validate)
    monkeypatch.setattr(hik_api.recording_schedule_manager, "reconcile", no_reconcile)
    monkeypatch.setattr(hik_api, "camera_runtime_coordinator", Coordinator(), raising=False)

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras/hik",
            json={
                "name": "hik-update-camera",
                "host": "10.0.0.81",
                "port": 8000,
                "username": "admin",
                "password": "old-secret",
                "channel": 1,
            },
        )
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])

        def is_running(value: int) -> bool:
            legacy_calls.append(("recorder-is-running", value))
            return False

        async def stop_event(value: int):
            legacy_calls.append(("event-stop", value))

        async def restart_motion(value: int):
            legacy_calls.append(("motion-restart", value))

        monkeypatch.setattr(hik_api.recorder_manager, "is_running", is_running)
        monkeypatch.setattr(hik_api.event_recording_manager, "stop_camera", stop_event)
        monkeypatch.setattr(hik_api.motion_detection_manager, "restart_camera", restart_motion)

        response = client.put(
            f"/api/cameras/hik/{camera_id}",
            json={
                "name": "hik-update-camera-renamed",
                "host": "10.0.0.82",
                "port": 8000,
                "username": "operator",
                "password": "new-secret",
                "channel": 3,
                "enabled": True,
                "auto_record": False,
                "timestamp_mode": "reconstruct",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "hik-update-camera-renamed"
        assert body["ip"] == "10.0.0.82"
        assert "new-secret" not in response.text
        assert coordinator_calls == [(camera_id, False)]
        assert legacy_calls == []

        metadata = asyncio.run(_metadata(camera_id))
        assert metadata is not None
        assert metadata.channel == 3


def test_hik_probe_preserves_bridge_runtime_unavailable_status(monkeypatch) -> None:
    async def fail_probe(_self, **_kwargs):
        raise hik_api.HikBridgeClientError(
            "HCNetSDK runtime is unavailable",
            status_code=503,
        )

    monkeypatch.setattr(hik_api.HikBridgeClient, "probe", fail_probe)

    with TestClient(app) as client:
        response = client.post(
            "/api/cameras/hik/probe",
            json={
                "host": "10.0.0.90",
                "port": 8000,
                "username": "admin",
                "password": "private-secret",
                "channel": 1,
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "HCNetSDK runtime is unavailable"
    assert "private-secret" not in response.text
