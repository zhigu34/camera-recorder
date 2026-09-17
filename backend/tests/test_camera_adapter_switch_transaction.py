from __future__ import annotations

import asyncio
import uuid

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


class _FailingRestoreCoordinator(_CoordinatorSpy):
    async def restore(
        self,
        camera_id: int,
        snapshot: RuntimeStopSnapshot,
        *,
        schedule_changed: bool = False,
    ) -> str:
        await super().restore(camera_id, snapshot, schedule_changed=schedule_changed)
        raise RuntimeError("runtime restore failed")


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


def _hik_discovered() -> HikProbeResult:
    return HikProbeResult(
        serial_number="HIK-TX-1",
        device_type=42,
        device_model="DS-2CD-TX",
        device_name="Transaction Gate",
        start_channel=1,
        analog_channel_count=1,
        digital_channel_count=0,
        channel=3,
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


def test_hik_switch_commit_failure_rolls_back_and_restores_old_runtime(monkeypatch) -> None:
    spy = _CoordinatorSpy()

    async def fake_probe(_payload):
        return _hik_discovered()

    async def fake_validate(_payload, _db):
        return _media()

    monkeypatch.setattr(hik_api, "_probe_hik", fake_probe)
    monkeypatch.setattr(hik_api, "_validate_main_stream", fake_validate)
    monkeypatch.setattr(hik_api, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        blocker = client.post("/api/cameras", json=_manual_payload("hik-switch-blocker"))
        assert blocker.status_code == 201, blocker.text
        blocker_name = blocker.json()["name"]

        created = client.post("/api/cameras", json=_manual_payload("hik-switch-commit-failure"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        response = client.put(
            f"/api/cameras/hik/{camera_id}",
            json={
                "name": blocker_name,
                "host": "203.0.113.61",
                "port": 8000,
                "username": "hik-user",
                "password": "hik-secret",
                "channel": 3,
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


def test_manual_switch_commit_failure_rolls_back_and_restores_old_runtime(monkeypatch) -> None:
    spy = _CoordinatorSpy()

    async def fake_manual_probe(**_kwargs):
        return _media()

    monkeypatch.setattr(onvif_api, "_validated_discovery", _validated_onvif)
    monkeypatch.setattr(onvif_api.recording_schedule_manager, "reconcile", _no_schedule_reconcile)
    monkeypatch.setattr(cameras_api, "probe_camera", fake_manual_probe, raising=False)
    monkeypatch.setattr(cameras_api, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        blocker = client.post("/api/cameras", json=_manual_payload("manual-switch-blocker"))
        assert blocker.status_code == 201, blocker.text
        blocker_name = blocker.json()["name"]

        created = client.post(
            "/api/cameras/onvif",
            json={
                "name": f"manual-switch-source-{uuid.uuid4().hex[:10]}",
                "host": "198.51.100.62",
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
                "name": blocker_name,
                "ip": "192.0.2.62",
                "rtsp_port": 9554,
                "username": "manual-user",
                "password": "manual-secret",
                "rtsp_path": "/new/main",
                "sub_rtsp_path": "/new/sub",
            },
        )
        after = asyncio.run(_snapshot(camera_id))

    assert response.status_code == 409, response.text
    assert spy.calls == [
        ("stop", camera_id, False),
        ("restore", camera_id, False),
    ]
    assert after == before


def test_post_commit_restore_failure_keeps_new_connection_persisted(monkeypatch) -> None:
    spy = _FailingRestoreCoordinator()
    monkeypatch.setattr(onvif_api, "_validated_discovery", _validated_onvif)
    monkeypatch.setattr(onvif_api, "camera_runtime_coordinator", spy)

    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post("/api/cameras", json=_manual_payload("restore-failure"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        response = client.put(
            f"/api/cameras/onvif/{camera_id}",
            json={
                "host": "198.51.100.63",
                "port": 80,
                "username": "onvif-user",
                "password": "onvif-secret",
                "enabled": False,
                "auto_record": False,
                "timestamp_mode": "native",
            },
        )
        after = asyncio.run(_snapshot(camera_id))

    assert response.status_code == 500, response.text
    assert spy.calls == [
        ("stop", camera_id, False),
        ("restore", camera_id, False),
    ]
    assert after["camera_id"] == before["camera_id"]
    assert after["connection_id"] == before["connection_id"]
    assert after["revision"] == before["revision"] + 1
    assert after["adapter"] == "onvif"
    assert after["rtsp"] is False
    assert after["onvif"] is True
    assert after["hik"] is False


def test_manual_switch_missing_target_fields_does_not_stop_or_mutate_old_connection(monkeypatch) -> None:
    spy = _CoordinatorSpy()
    monkeypatch.setattr(onvif_api, "_validated_discovery", _validated_onvif)
    monkeypatch.setattr(onvif_api.recording_schedule_manager, "reconcile", _no_schedule_reconcile)
    monkeypatch.setattr(cameras_api, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras/onvif",
            json={
                "name": f"manual-incomplete-{uuid.uuid4().hex[:10]}",
                "host": "198.51.100.64",
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
                "ip": "192.0.2.64",
                "password": "manual-secret",
            },
        )
        after = asyncio.run(_snapshot(camera_id))

    assert response.status_code == 422, response.text
    assert spy.calls == []
    assert after == before
