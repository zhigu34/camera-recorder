import asyncio

from fastapi.testclient import TestClient

from app.api import onvif_cameras as onvif_api
from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.main import app
from app.models import Camera, OnvifDeviceMetadata
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


async def _connection_snapshot(camera_id: int) -> dict:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        assert camera is not None
        connection = camera.connection
        assert connection is not None
        config = connection.onvif_config
        assert config is not None
        metadata = await db.get(OnvifDeviceMetadata, camera_id)
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
                "device_service_url": config.device_service_url,
                "device_uuid": config.device_uuid,
                "capabilities_json": config.capabilities_json,
                "profiles_json": config.profiles_json,
                "recording_profile_token": config.recording_profile_token,
                "preview_profile_token": config.preview_profile_token,
                "detection_profile_token": config.detection_profile_token,
                "recording_uri": config.recording_uri,
                "preview_uri": config.preview_uri,
                "detection_uri": config.detection_uri,
            },
            "legacy_metadata_present": metadata is not None,
            "legacy": {
                "connection_type": camera.connection_type,
                "ip": camera.ip,
                "rtsp_port": camera.rtsp_port,
                "username": camera.username,
                "password_encrypted": camera.password_encrypted,
                "rtsp_path": camera.rtsp_path,
                "sub_rtsp_path": camera.sub_rtsp_path,
            },
        }


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


def test_onvif_camera_creation_persists_current_connection_without_legacy_metadata(monkeypatch) -> None:
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

        snapshot = asyncio.run(_connection_snapshot(camera_id))
        assert snapshot["camera_id"] == camera_id
        assert snapshot["adapter"] == "onvif"
        assert snapshot["host"] == "10.0.0.20"
        assert snapshot["username"] == "operator@site"
        assert decrypt_secret(snapshot["password_encrypted"]) == "p:ss/word"
        assert snapshot["revision"] == 1
        assert snapshot["verification_status"] == "verified"
        assert snapshot["verified_at"] is not None
        assert snapshot["legacy_metadata_present"] is False
        assert snapshot["config"]["device_service_url"] == DISCOVERED.device_service_url
        assert snapshot["config"]["capabilities_json"] == DISCOVERED.capabilities
        assert snapshot["config"]["recording_profile_token"] == "main"
        assert snapshot["config"]["preview_profile_token"] == "sub"
        assert snapshot["config"]["recording_uri"] == "rtsp://10.0.0.20:554/main"
        assert snapshot["config"]["preview_uri"] == "rtsp://10.0.0.20:554/sub"
        assert all(
            "@" not in uri
            for uri in (
                snapshot["config"]["recording_uri"],
                snapshot["config"]["preview_uri"],
                snapshot["config"]["detection_uri"],
            )
            if uri
        )
        assert snapshot["legacy"] == {
            "connection_type": "onvif",
            "ip": "10.0.0.20",
            "rtsp_port": 554,
            "username": "operator@site",
            "password_encrypted": snapshot["password_encrypted"],
            "rtsp_path": "/main",
            "sub_rtsp_path": "/sub",
        }


def test_onvif_camera_update_reuses_connection_and_replaces_current_config(monkeypatch) -> None:
    discoveries = [DISCOVERED, UPDATED_DISCOVERED]
    stream_calls: list[str] = []
    runtime_reload_calls: list[tuple[int, bool]] = []

    async def fake_onvif_probe(_payload):
        return discoveries.pop(0)

    async def fake_stream_probe(*, stream_uri: str, rtsp_timeout_us: int):
        stream_calls.append(stream_uri)
        assert rtsp_timeout_us > 0
        return _media_probe_result(codec="hevc", fps=25 if "main-v2" in stream_uri else 20)

    async def no_reconcile():
        return None

    async def reload_runtime(camera_id: int, *, schedule_changed: bool = False) -> str:
        runtime_reload_calls.append((camera_id, schedule_changed))
        return "running"

    monkeypatch.setattr(onvif_api, "_probe_onvif", fake_onvif_probe)
    monkeypatch.setattr(onvif_api, "probe_stream_uri", fake_stream_probe)
    monkeypatch.setattr(onvif_api.recording_schedule_manager, "reconcile", no_reconcile)
    monkeypatch.setattr(onvif_api.camera_runtime_coordinator, "reload", reload_runtime)

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
        before = asyncio.run(_connection_snapshot(camera_id))
        assert before["revision"] == 1

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
        assert body["id"] == camera_id
        assert body["name"] == "onvif-update-camera-renamed"
        assert body["model"] == "DoorCam 4K Rev B"
        assert body["ip"] == "10.0.0.21"
        assert body["rtsp_port"] == 8554
        assert body["rtsp_path"] == "/main-v2"
        assert body["sub_rtsp_path"] == "/sub-v2"
        assert body["video_codec"] == "hevc"
        assert stream_calls[-1] == "rtsp://operator:new-secret@10.0.0.21:8554/main-v2"
        assert runtime_reload_calls == [(camera_id, False)]

        after = asyncio.run(_connection_snapshot(camera_id))
        assert after["camera_id"] == camera_id
        assert after["connection_id"] == before["connection_id"]
        assert after["adapter"] == "onvif"
        assert after["host"] == "10.0.0.21"
        assert after["username"] == "operator"
        assert decrypt_secret(after["password_encrypted"]) == "new-secret"
        assert after["revision"] == 2
        assert after["verification_status"] == "verified"
        assert after["verified_at"] is not None
        assert after["legacy_metadata_present"] is False
        assert after["config"]["device_service_url"] == UPDATED_DISCOVERED.device_service_url
        assert after["config"]["recording_profile_token"] == "main-v2"
        assert after["config"]["preview_profile_token"] == "sub-v2"
        assert after["config"]["recording_uri"] == "rtsp://10.0.0.21:8554/main-v2"
        assert after["config"]["preview_uri"] == "rtsp://10.0.0.21:8554/sub-v2"
        assert all(
            "@" not in uri
            for uri in (
                after["config"]["recording_uri"],
                after["config"]["preview_uri"],
                after["config"]["detection_uri"],
            )
            if uri
        )


def test_onvif_rediscovery_reloads_runtime_without_incrementing_revision(monkeypatch) -> None:
    refreshed = OnvifProbeResult.model_validate(
        {
            **DISCOVERED.model_dump(),
            "profiles": [
                {
                    "token": "main-refreshed",
                    "name": "Main refreshed",
                    "encoding": "H265",
                    "width": 3840,
                    "height": 2160,
                    "fps": 25,
                    "uri": "rtsp://10.0.0.20:8554/main-refreshed",
                },
                {
                    "token": "sub-refreshed",
                    "name": "Sub refreshed",
                    "encoding": "H264",
                    "width": 640,
                    "height": 360,
                    "fps": 12,
                    "uri": "rtsp://10.0.0.20:8554/sub-refreshed",
                },
            ],
            "recording_profile_token": "main-refreshed",
            "preview_profile_token": "sub-refreshed",
            "detection_profile_token": "sub-refreshed",
            "recording_uri": "rtsp://10.0.0.20:8554/main-refreshed",
            "preview_uri": "rtsp://10.0.0.20:8554/sub-refreshed",
            "detection_uri": "rtsp://10.0.0.20:8554/sub-refreshed",
        }
    )
    discoveries = [DISCOVERED, refreshed]
    runtime_reload_calls: list[tuple[int, bool]] = []

    async def fake_onvif_probe(_payload):
        return discoveries.pop(0)

    async def fake_stream_probe(*, stream_uri: str, rtsp_timeout_us: int):
        assert stream_uri
        assert rtsp_timeout_us > 0
        return _media_probe_result(codec="hevc", fps=25)

    async def no_reconcile():
        return None

    async def reload_runtime(camera_id: int, *, schedule_changed: bool = False) -> str:
        runtime_reload_calls.append((camera_id, schedule_changed))
        return "running"

    monkeypatch.setattr(onvif_api, "_probe_onvif", fake_onvif_probe)
    monkeypatch.setattr(onvif_api, "probe_stream_uri", fake_stream_probe)
    monkeypatch.setattr(onvif_api.recording_schedule_manager, "reconcile", no_reconcile)
    monkeypatch.setattr(onvif_api.camera_runtime_coordinator, "reload", reload_runtime)

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras/onvif",
            json={
                "name": "onvif-rediscovery-camera",
                "host": "10.0.0.20",
                "port": 80,
                "username": "admin",
                "password": "same-secret",
            },
        )
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_connection_snapshot(camera_id))
        assert before["revision"] == 1

        response = client.put(
            f"/api/cameras/onvif/{camera_id}",
            json={
                "host": "10.0.0.20",
                "port": 80,
                "username": "admin",
                "password": "same-secret",
            },
        )
        assert response.status_code == 200, response.text
        after = asyncio.run(_connection_snapshot(camera_id))
        assert after["revision"] == 1
        assert after["config"]["recording_profile_token"] == "main-refreshed"
        assert after["config"]["recording_uri"] == "rtsp://10.0.0.20:8554/main-refreshed"
        assert runtime_reload_calls == [(camera_id, False)]
