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

UPDATED_DISCOVERED = OnvifProbeResult.model_validate(
    {
        **DISCOVERED.model_dump(),
        "model": "DoorCam 4K Rev B",
        "device_service_url": "http://10.0.0.21:8080/onvif/device_service",
        "capabilities": {
            "media_xaddr": "http://10.0.0.21:8080/onvif/media_service",
            "events_xaddr": "http://10.0.0.21:8080/onvif/events_service",
            "ptz_xaddr": None,
        },
        "profiles": [
            {
                "token": "main-v2",
                "name": "Main v2",
                "encoding": "H265",
                "width": 3840,
                "height": 2160,
                "fps": 25,
                "uri": "rtsp://10.0.0.21:8554/main-v2",
            },
            {
                "token": "sub-v2",
                "name": "Sub v2",
                "encoding": "H264",
                "width": 640,
                "height": 360,
                "fps": 12,
                "uri": "rtsp://10.0.0.21:8554/sub-v2",
            },
        ],
        "recording_profile_token": "main-v2",
        "preview_profile_token": "sub-v2",
        "detection_profile_token": "sub-v2",
        "recording_uri": "rtsp://10.0.0.21:8554/main-v2",
        "preview_uri": "rtsp://10.0.0.21:8554/sub-v2",
        "detection_uri": "rtsp://10.0.0.21:8554/sub-v2",
    }
)


async def _metadata(camera_id: int) -> OnvifDeviceMetadata | None:
    async with SessionLocal() as db:
        return await db.get(OnvifDeviceMetadata, camera_id)


def _media_probe_result(*, codec: str = "h264", fps: int = 20) -> dict:
    return {
        "ok": True,
        "video_codec": codec,
        "video_profile": "High",
        "width": 3840,
        "height": 2160,
        "fps_num": fps,
        "fps_den": 1,
        "fps": float(fps),
        "pixel_format": "yuv420p",
        "has_b_frames": 0,
        "video_time_base": "1/90000",
        "audio_codec": "aac",
        "audio_profile": "LC",
        "sample_rate": 48000,
        "channels": 1,
        "audio_frame_samples": 1024,
    }


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
        return _media_probe_result()

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


def test_onvif_camera_update_reprobes_profiles_and_replaces_safe_metadata(monkeypatch) -> None:
    discoveries = [DISCOVERED, UPDATED_DISCOVERED]
    stream_calls: list[str] = []
    recorder_calls: list[tuple[str, int]] = []

    async def fake_onvif_probe(_payload):
        return discoveries.pop(0)

    async def fake_stream_probe(*, stream_uri: str, rtsp_timeout_us: int):
        stream_calls.append(stream_uri)
        assert rtsp_timeout_us > 0
        return _media_probe_result(codec="hevc", fps=25 if "main-v2" in stream_uri else 20)

    async def no_reconcile():
        return None

    async def no_motion_restart(_camera_id: int):
        return None

    def recorder_is_running(_camera_id: int) -> bool:
        return True

    async def stop_recorder(camera_id: int):
        recorder_calls.append(("stop", camera_id))
        return {"camera_id": camera_id, "state": "STOPPED", "pid": None}

    async def start_regular(camera):
        recorder_calls.append(("start", int(camera.id)))
        return {"camera_id": int(camera.id), "state": "RECORDING", "pid": 1}

    monkeypatch.setattr(onvif_api, "_probe_onvif", fake_onvif_probe)
    monkeypatch.setattr(onvif_api, "probe_stream_uri", fake_stream_probe)
    monkeypatch.setattr(onvif_api.recording_schedule_manager, "reconcile", no_reconcile)
    monkeypatch.setattr(onvif_api.motion_detection_manager, "restart_camera", no_motion_restart)
    monkeypatch.setattr(onvif_api.recorder_manager, "is_running", recorder_is_running)
    monkeypatch.setattr(onvif_api.recorder_manager, "stop", stop_recorder)
    monkeypatch.setattr(onvif_api, "start_regular_recorder", start_regular)

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras/onvif",
            json={
                "name": "onvif-update-camera",
                "host": "10.0.0.20",
                "port": 80,
                "username": "admin",
                "password": "old-secret",
                "enabled": True,
                "auto_record": False,
                "timestamp_mode": "reconstruct",
            },
        )
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])

        response = client.put(
            f"/api/cameras/onvif/{camera_id}",
            json={
                "name": "onvif-update-camera-renamed",
                "host": "10.0.0.21",
                "port": 8080,
                "username": "operator",
                "password": "new-secret",
                "enabled": True,
                "auto_record": False,
                "timestamp_mode": "reconstruct",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "onvif-update-camera-renamed"
        assert body["model"] == "DoorCam 4K Rev B"
        assert body["ip"] == "10.0.0.21"
        assert body["rtsp_port"] == 8554
        assert body["rtsp_path"] == "/main-v2"
        assert body["sub_rtsp_path"] == "/sub-v2"
        assert body["video_codec"] == "hevc"
        assert stream_calls[-1] == "rtsp://operator:new-secret@10.0.0.21:8554/main-v2"
        assert recorder_calls == [("stop", camera_id), ("start", camera_id)]

        metadata = asyncio.run(_metadata(camera_id))
        assert metadata is not None
        assert metadata.device_service_url == "http://10.0.0.21:8080/onvif/device_service"
        assert metadata.recording_profile_token == "main-v2"
        assert metadata.preview_profile_token == "sub-v2"
        assert metadata.recording_uri == "rtsp://10.0.0.21:8554/main-v2"
        assert "operator" not in metadata.recording_uri
        assert "secret" not in metadata.recording_uri
