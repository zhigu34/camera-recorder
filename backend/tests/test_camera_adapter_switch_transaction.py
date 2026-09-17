from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from app.api import onvif_cameras as onvif_api
from app.core.database import SessionLocal
from app.main import app
from app.models import Camera
from app.schemas.camera import OnvifProbeResult
from app.services.camera_runtime_coordinator import RuntimeStopSnapshot


class _CoordinatorSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.snapshot = RuntimeStopSnapshot(was_recording=False, recording_owner=None)

    async def stop_all(self, camera_id: int, *, forget_schedule: bool = False):
        self.calls.append(("stop", camera_id, forget_schedule))
        return self.snapshot

    async def restore(
        self,
        camera_id: int,
        snapshot: RuntimeStopSnapshot,
        *,
        schedule_changed: bool = False,
    ) -> str:
        assert snapshot is self.snapshot
        self.calls.append(("restore", camera_id, schedule_changed))
        return "running"


async def _snapshot(camera_id: int) -> dict:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        assert camera is not None
        connection = camera.connection
        assert connection is not None
        return {
            "camera_id": camera.id,
            "name": camera.name,
            "connection_id": connection.id,
            "adapter": connection.adapter,
            "revision": connection.revision,
            "host": connection.host,
            "rtsp": connection.rtsp_config is not None,
            "onvif": connection.onvif_config is not None,
            "hik": connection.hik_config is not None,
            "legacy_type": camera.connection_type,
        }


def _manual_payload(prefix: str) -> dict:
    return {
        "name": f"{prefix}-{uuid.uuid4().hex[:10]}",
        "ip": "192.0.2.10",
        "rtsp_port": 8554,
        "username": "rtsp-user",
        "password": "rtsp-secret",
        "rtsp_path": "/live/main",
        "sub_rtsp_path": "/live/sub",
        "enabled": False,
        "auto_record": False,
        "timestamp_mode": "native",
    }


def _onvif_discovered(host: str) -> OnvifProbeResult:
    main_uri = f"rtsp://{host}:8554/onvif/main"
    sub_uri = f"rtsp://{host}:8554/onvif/sub"
    return OnvifProbeResult.model_validate(
        {
            "manufacturer": "Acme",
            "model": "SwitchCam",
            "firmware_version": "1.0",
            "serial_number": "SW-TX-1",
            "hardware_id": "HW-TX-1",
            "device_uuid": f"uuid-{host}",
            "device_service_url": f"http://{host}:80/onvif/device_service",
            "capabilities": {"media_xaddr": f"http://{host}/onvif/media"},
            "profiles": [
                {
                    "token": "main",
                    "name": "Main",
                    "encoding": "H264",
                    "width": 1920,
                    "height": 1080,
                    "fps": 20,
                    "uri": main_uri,
                },
                {
                    "token": "sub",
                    "name": "Sub",
                    "encoding": "H264",
                    "width": 640,
                    "height": 360,
                    "fps": 10,
                    "uri": sub_uri,
                },
            ],
            "recording_profile_token": "main",
            "preview_profile_token": "sub",
            "detection_profile_token": "sub",
            "recording_uri": main_uri,
            "preview_uri": sub_uri,
            "detection_uri": sub_uri,
        }
    )


def _media() -> dict:
    return {
        "ok": True,
        "video_codec": "h264",
        "video_profile": "High",
        "width": 1920,
        "height": 1080,
        "fps_num": 20,
        "fps_den": 1,
        "fps": 20.0,
        "pixel_format": "yuv420p",
        "has_b_frames": 0,
        "video_time_base": "1/90000",
        "audio_codec": None,
        "audio_profile": None,
        "sample_rate": None,
        "channels": None,
        "audio_frame_samples": None,
    }


async def _validated_onvif(payload, db):
    del db
    discovered = _onvif_discovered(payload.host)
    return discovered, _media(), discovered.profiles[0], payload.host, 8554, "/onvif/main", "/onvif/sub"


def test_cross_adapter_commit_failure_rolls_back_and_restores_old_runtime(monkeypatch) -> None:
    spy = _CoordinatorSpy()
    monkeypatch.setattr(onvif_api, "_validated_discovery", _validated_onvif)
    monkeypatch.setattr(onvif_api, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        blocker = client.post("/api/cameras", json=_manual_payload("switch-blocker"))
        assert blocker.status_code == 201, blocker.text
        blocker_name = blocker.json()["name"]

        created = client.post("/api/cameras", json=_manual_payload("switch-commit-failure"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        response = client.put(
            f"/api/cameras/onvif/{camera_id}",
            json={
                "name": blocker_name,
                "host": "198.51.100.60",
                "port": 80,
                "username": "onvif-user",
                "password": "onvif-secret",
                "enabled": False,
                "auto_record": False,
                "timestamp_mode": "native",
            },
        )
        after = asyncio.run(_snapshot(camera_id))

    assert response.status_code == 409, response.text
    assert spy.calls == [
        ("stop", camera_id, False),
        ("restore", camera_id, False),
    ]
    assert after == before
