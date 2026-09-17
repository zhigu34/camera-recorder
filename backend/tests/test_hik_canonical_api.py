import asyncio

from fastapi.testclient import TestClient

from app.api import hik_cameras as hik_api
from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.main import app
from app.models import Camera, HikDeviceMetadata
from app.schemas.hikvision import HikProbeResult


DISCOVERED = HikProbeResult(
    serial_number="HIK-CANONICAL-42",
    device_type=42,
    device_model="DS-2CD-Canonical",
    device_name="Canonical Gate",
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


async def _snapshot(camera_id: int) -> dict:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        assert camera is not None
        connection = camera.connection
        assert connection is not None
        config = connection.hik_config
        assert config is not None
        shadow = await db.get(HikDeviceMetadata, camera_id)
        return {
            "camera_id": camera.id,
            "connection_id": connection.id,
            "adapter": connection.adapter,
            "host": connection.host,
            "username": connection.username,
            "password_encrypted": connection.password_encrypted,
            "revision": connection.revision,
            "verification_status": connection.verification_status,
            "verified_at": connection.verified_at,
            "config": {
                "sdk_port": config.sdk_port,
                "channel": config.channel,
                "main_stream_type": config.main_stream_type,
                "sub_stream_type": config.sub_stream_type,
                "device_serial": config.device_serial,
                "device_model": config.device_model,
                "device_name": config.device_name,
            },
            "shadow": None
            if shadow is None
            else {
                "sdk_port": shadow.sdk_port,
                "channel": shadow.channel,
                "device_serial": shadow.device_serial,
            },
        }


def test_hik_create_persists_canonical_connection_and_legacy_shadow(monkeypatch) -> None:
    async def fake_probe(_payload):
        return DISCOVERED

    async def fake_validate(_payload, _db):
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
                "name": "hik-canonical-api-camera",
                "host": "10.0.0.88",
                "port": 9000,
                "username": "operator",
                "password": "canonical-secret",
                "channel": 4,
                "enabled": True,
                "auto_record": False,
                "timestamp_mode": "reconstruct",
            },
        )

    assert response.status_code == 201, response.text
    camera_id = int(response.json()["id"])
    snapshot = asyncio.run(_snapshot(camera_id))

    assert snapshot["camera_id"] == camera_id
    assert snapshot["connection_id"] > 0
    assert snapshot["adapter"] == "hik_sdk"
    assert snapshot["host"] == "10.0.0.88"
    assert snapshot["username"] == "operator"
    assert decrypt_secret(snapshot["password_encrypted"]) == "canonical-secret"
    assert snapshot["revision"] == 1
    assert snapshot["verification_status"] == "verified"
    assert snapshot["verified_at"] is not None
    assert snapshot["config"] == {
        "sdk_port": 9000,
        "channel": 4,
        "main_stream_type": 0,
        "sub_stream_type": 1,
        "device_serial": "HIK-CANONICAL-42",
        "device_model": "DS-2CD-Canonical",
        "device_name": "Canonical Gate",
    }
    assert snapshot["shadow"] == {
        "sdk_port": 9000,
        "channel": 4,
        "device_serial": "HIK-CANONICAL-42",
    }
