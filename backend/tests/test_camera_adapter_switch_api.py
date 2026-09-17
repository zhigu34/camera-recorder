from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import cameras as cameras_api
from app.api import hik_cameras as hik_api
from app.api import onvif_cameras as onvif_api
from app.core.database import SessionLocal
from app.main import app
from app.models import Camera
from app.schemas.camera import OnvifProbeResult
from app.schemas.hikvision import HikProbeResult
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

    async def reload(self, camera_id: int, *, schedule_changed: bool = False) -> str:
        self.calls.append(("reload", camera_id, schedule_changed))
        return "running"


async def _snapshot(camera_id: int) -> dict:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        assert camera is not None
        connection = camera.connection
        assert connection is not None
        return {
            "camera_id": camera.id,
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
            "serial_number": "SW-1",
            "hardware_id": "HW-1",
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


async def _no_schedule_reconcile() -> None:
    return None


def test_manual_rtsp_to_onvif_switch_validates_then_stops_persists_and_restores(monkeypatch) -> None:
    spy = _CoordinatorSpy()
    validation_calls: list[str] = []

    async def validated(payload, db):
        validation_calls.append(payload.host)
        return await _validated_onvif(payload, db)

    monkeypatch.setattr(onvif_api, "_validated_discovery", validated)
    monkeypatch.setattr(onvif_api, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_manual_payload("switch-to-onvif"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        response = client.put(
            f"/api/cameras/onvif/{camera_id}",
            json={
                "host": "198.51.100.20",
                "port": 80,
                "username": "onvif-user",
                "password": "onvif-secret",
                "enabled": False,
                "auto_record": False,
                "timestamp_mode": "native",
            },
        )

        assert response.status_code == 200, response.text
        after = asyncio.run(_snapshot(camera_id))

    assert validation_calls == ["198.51.100.20"]
    assert spy.calls == [("stop", camera_id, False), ("restore", camera_id, False)]
    assert after["camera_id"] == before["camera_id"]
    assert after["connection_id"] == before["connection_id"]
    assert after["revision"] == before["revision"] + 1
    assert after["adapter"] == "onvif"
    assert after["rtsp"] is False
    assert after["onvif"] is True
    assert after["hik"] is False
    assert after["legacy_type"] == "onvif"


def test_manual_rtsp_to_hik_switch_validates_then_stops_persists_and_restores(monkeypatch) -> None:
    spy = _CoordinatorSpy()
    validation_calls: list[str] = []
    discovered = HikProbeResult(
        serial_number="HIK-SW-1",
        device_type=42,
        device_model="DS-2CD-Switch",
        device_name="Switch Gate",
        start_channel=1,
        analog_channel_count=1,
        digital_channel_count=0,
        channel=3,
    )

    async def fake_probe(payload):
        validation_calls.append(f"probe:{payload.host}")
        return discovered

    async def fake_validate(payload, db):
        del db
        validation_calls.append(f"media:{payload.host}")
        return _media()

    monkeypatch.setattr(hik_api, "_probe_hik", fake_probe)
    monkeypatch.setattr(hik_api, "_validate_main_stream", fake_validate)
    monkeypatch.setattr(hik_api, "camera_runtime_coordinator", spy, raising=False)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_manual_payload("switch-to-hik"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        response = client.put(
            f"/api/cameras/hik/{camera_id}",
            json={
                "host": "203.0.113.30",
                "port": 9000,
                "username": "hik-user",
                "password": "hik-secret",
                "channel": 3,
                "enabled": False,
                "auto_record": False,
                "timestamp_mode": "native",
            },
        )

        assert response.status_code == 200, response.text
        after = asyncio.run(_snapshot(camera_id))

    assert validation_calls == ["probe:203.0.113.30", "media:203.0.113.30"]
    assert spy.calls == [("stop", camera_id, False), ("restore", camera_id, False)]
    assert after["camera_id"] == before["camera_id"]
    assert after["connection_id"] == before["connection_id"]
    assert after["revision"] == before["revision"] + 1
    assert after["adapter"] == "hik_sdk"
    assert after["rtsp"] is False
    assert after["onvif"] is False
    assert after["hik"] is True
    assert after["legacy_type"] == "hik_sdk"


def test_onvif_to_manual_rtsp_switch_requires_full_target_and_restores_runtime(monkeypatch) -> None:
    spy = _CoordinatorSpy()
    probe_calls: list[tuple] = []

    async def fake_manual_probe(**kwargs):
        probe_calls.append(
            (
                kwargs["ip"],
                kwargs["port"],
                kwargs["username"],
                kwargs["password"],
                kwargs["rtsp_path"],
            )
        )
        return _media()

    monkeypatch.setattr(onvif_api, "_validated_discovery", _validated_onvif)
    monkeypatch.setattr(onvif_api.recording_schedule_manager, "reconcile", _no_schedule_reconcile)
    monkeypatch.setattr(cameras_api, "probe_camera", fake_manual_probe, raising=False)
    monkeypatch.setattr(cameras_api, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras/onvif",
            json={
                "name": f"switch-to-manual-{uuid.uuid4().hex[:10]}",
                "host": "198.51.100.40",
                "port": 80,
                "username": "onvif-user",
                "password": "onvif-secret",
                "enabled": False,
                "auto_record": False,
                "timestamp_mode": "native",
            },
        )
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        response = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "ip": "192.0.2.99",
                "rtsp_port": 9554,
                "username": "manual-user",
                "password": "manual-secret",
                "rtsp_path": "/new/main",
                "sub_rtsp_path": "/new/sub",
            },
        )

        assert response.status_code == 200, response.text
        after = asyncio.run(_snapshot(camera_id))

    assert probe_calls == [
        ("192.0.2.99", 9554, "manual-user", "manual-secret", "/new/main")
    ]
    assert spy.calls == [("stop", camera_id, False), ("restore", camera_id, False)]
    assert after["camera_id"] == before["camera_id"]
    assert after["connection_id"] == before["connection_id"]
    assert after["revision"] == before["revision"] + 1
    assert after["adapter"] == "manual_rtsp"
    assert after["rtsp"] is True
    assert after["onvif"] is False
    assert after["hik"] is False
    assert after["legacy_type"] == "manual_rtsp"


def test_cross_adapter_validation_failure_does_not_stop_or_mutate_current_connection(monkeypatch) -> None:
    spy = _CoordinatorSpy()

    async def invalid_target(payload, db):
        del payload, db
        raise HTTPException(status_code=502, detail="target validation failed")

    monkeypatch.setattr(onvif_api, "_validated_discovery", invalid_target)
    monkeypatch.setattr(onvif_api, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_manual_payload("switch-validation-failure"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        response = client.put(
            f"/api/cameras/onvif/{camera_id}",
            json={
                "host": "198.51.100.50",
                "port": 80,
                "username": "onvif-user",
                "password": "bad-secret",
                "enabled": False,
                "auto_record": False,
                "timestamp_mode": "native",
            },
        )
        after = asyncio.run(_snapshot(camera_id))

    assert response.status_code == 502, response.text
    assert response.json()["detail"] == "target validation failed"
    assert spy.calls == []
    assert after == before
