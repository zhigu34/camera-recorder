import asyncio

from fastapi.testclient import TestClient

from app.api import onvif_cameras as onvif_api
from app.core.database import SessionLocal
from app.main import app
from app.models.onvif import OnvifDeviceMetadata
from app.schemas.camera import OnvifProbeResult


DISCOVERED = OnvifProbeResult.model_validate(
    {
        "manufacturer": "Acme",
        "model": "DoorCam 4K",
        "firmware_version": "2.4.1",
        "serial_number": "SN-42",
        "hardware_id": "HW-9",
        "device_uuid": None,
        "device_service_url": "http://10.0.0.20:80/onvif/device_service",
        "capabilities": {
            "media_xaddr": "http://10.0.0.20/onvif/media_service",
            "events_xaddr": "http://10.0.0.20/onvif/events_service",
            "ptz_xaddr": None,
        },
        "profiles": [
            {
                "token": "main",
                "name": "Main",
                "encoding": "H264",
                "width": 3840,
                "height": 2160,
                "fps": 20,
                "uri": "rtsp://10.0.0.20:554/main",
            },
            {
                "token": "sub",
                "name": "Sub",
                "encoding": "H264",
                "width": 640,
                "height": 360,
                "fps": 10,
                "uri": "rtsp://10.0.0.20:554/sub",
            },
        ],
        "recording_profile_token": "main",
        "preview_profile_token": "sub",
        "detection_profile_token": "sub",
        "recording_uri": "rtsp://10.0.0.20:554/main",
        "preview_uri": "rtsp://10.0.0.20:554/sub",
        "detection_uri": "rtsp://10.0.0.20:554/sub",
    }
)


async def _metadata(camera_id: int) -> OnvifDeviceMetadata | None:
    async with SessionLocal() as db:
        return await db.get(OnvifDeviceMetadata, camera_id)


def test_onvif_camera_creation_revalidates_media_and_persists_safe_metadata(monkeypatch) -> None:
    probe_calls = 0
    stream_calls: list[str] = []

    async def fake_onvif_probe(_payload):
        nonlocal probe_calls
        probe_calls += 1
        return DISCOVERED

    async def fake_stream_probe(*, stream_uri: str, rtsp_timeout_us: int):
        stream_calls.append(stream_uri)
        assert rtsp_timeout_us > 0
        return {
            "ok": True,
            "video_codec": "h264",
            "video_profile": "High",
            "width": 3840,
            "height": 2160,
            "fps_num": 20,
            "fps_den": 1,
            "fps": 20.0,
            "pixel_format": "yuv420p",
            "has_b_frames": 0,
            "video_time_base": "1/90000",
            "audio_codec": "aac",
            "audio_profile": "LC",
            "sample_rate": 48000,
            "channels": 1,
            "audio_frame_samples": 1024,
        }

    async def no_reconcile():
        return None

    monkeypatch.setattr(onvif_api, "_probe_onvif", fake_onvif_probe)
    monkeypatch.setattr(onvif_api, "probe_stream_uri", fake_stream_probe)
    monkeypatch.setattr(onvif_api.recording_schedule_manager, "reconcile", no_reconcile)

    with TestClient(app) as client:
        response = client.post(
            "/api/cameras/onvif",
            json={
                "name": "onvif-api-camera",
                "host": "10.0.0.20",
                "port": 80,
                "username": "operator@site",
                "password": "p:ss/word",
                "enabled": True,
                "auto_record": False,
                "timestamp_mode": "reconstruct",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        camera_id = int(body["id"])
        assert body["connection_type"] == "onvif"
        assert body["manufacturer"] == "Acme"
        assert body["model"] == "DoorCam 4K"
        assert body["rtsp_path"] == "/main"
        assert body["sub_rtsp_path"] == "/sub"
        assert body["video_codec"] == "h264"
        assert body["fps_num"] == 20
        assert probe_calls == 1
        assert stream_calls == [
            "rtsp://operator%40site:p%3Ass%2Fword@10.0.0.20:554/main"
        ]

        metadata = asyncio.run(_metadata(camera_id))
        assert metadata is not None
        assert metadata.recording_profile_token == "main"
        assert metadata.preview_profile_token == "sub"
        assert metadata.recording_uri == "rtsp://10.0.0.20:554/main"
        assert "operator" not in metadata.recording_uri
        assert "word" not in metadata.recording_uri
