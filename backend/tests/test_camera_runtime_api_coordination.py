from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.api import cameras as cameras_api
from app.api import onvif_cameras as onvif_api
from app.main import app
from app.schemas.camera import OnvifProbeResult


class _CoordinatorSpy:
    def __init__(self) -> None:
        self.reload_calls: list[tuple[int, bool]] = []
        self.stop_calls: list[tuple[int, bool]] = []

    async def reload(self, camera_id: int, *, schedule_changed: bool = False) -> str:
        self.reload_calls.append((camera_id, schedule_changed))
        return "running"

    async def stop_all(self, camera_id: int, *, forget_schedule: bool = False):
        self.stop_calls.append((camera_id, forget_schedule))
        return None


def _manual_payload(prefix: str) -> dict:
    return {
        "name": f"{prefix}-{uuid.uuid4().hex[:10]}",
        "ip": "192.0.2.70",
        "rtsp_port": 554,
        "username": "admin",
        "password": "secret",
        "rtsp_path": "/main",
        "enabled": False,
        "auto_record": False,
        "timestamp_mode": "native",
    }


def test_manual_rtsp_update_reloads_only_for_connection_or_runtime_policy(monkeypatch) -> None:
    spy = _CoordinatorSpy()
    monkeypatch.setattr(cameras_api, "camera_runtime_coordinator", spy, raising=False)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_manual_payload("runtime-coordinator-rtsp"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])

        connection_update = client.put(
            f"/api/cameras/{camera_id}",
            json={"ip": "192.0.2.71", "rtsp_path": "/main-v2"},
        )
        assert connection_update.status_code == 200, connection_update.text
        assert spy.reload_calls == [(camera_id, False)]

        metadata_update = client.put(
            f"/api/cameras/{camera_id}",
            json={"name": f"runtime-coordinator-renamed-{uuid.uuid4().hex[:8]}"},
        )
        assert metadata_update.status_code == 200, metadata_update.text
        assert spy.reload_calls == [(camera_id, False)]

        policy_update = client.put(f"/api/cameras/{camera_id}", json={"enabled": True})
        assert policy_update.status_code == 200, policy_update.text
        assert spy.reload_calls == [(camera_id, False), (camera_id, True)]

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204, deleted.text


def test_camera_delete_uses_coordinator_instead_of_direct_manager_calls(monkeypatch) -> None:
    spy = _CoordinatorSpy()
    legacy_calls: list[str] = []
    monkeypatch.setattr(cameras_api, "camera_runtime_coordinator", spy, raising=False)

    async def legacy_motion(camera_id: int) -> None:
        legacy_calls.append(f"motion:{camera_id}")

    async def legacy_event(camera_id: int) -> None:
        legacy_calls.append(f"event:{camera_id}")

    async def legacy_recorder(camera_id: int):
        legacy_calls.append(f"recorder:{camera_id}")
        return {"camera_id": camera_id, "state": "STOPPED"}

    def legacy_forget(camera_id: int) -> None:
        legacy_calls.append(f"schedule:{camera_id}")

    monkeypatch.setattr(cameras_api.motion_detection_manager, "stop_camera", legacy_motion)
    monkeypatch.setattr(cameras_api.event_recording_manager, "stop_camera", legacy_event)
    monkeypatch.setattr(cameras_api.recorder_manager, "is_running", lambda _camera_id: True)
    monkeypatch.setattr(cameras_api.recorder_manager, "stop", legacy_recorder)
    monkeypatch.setattr(cameras_api.recording_schedule_manager, "forget", legacy_forget)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_manual_payload("runtime-coordinator-delete"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204, deleted.text

    assert spy.stop_calls == [(camera_id, True)]
    assert legacy_calls == []


def _discovered(host: str) -> OnvifProbeResult:
    uri = f"rtsp://{host}:554/main"
    return OnvifProbeResult.model_validate(
        {
            "manufacturer": "Acme",
            "model": "RuntimeCam",
            "firmware_version": "1.0",
            "serial_number": "RC-1",
            "hardware_id": "HW-1",
            "device_uuid": None,
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
                    "uri": uri,
                }
            ],
            "recording_profile_token": "main",
            "preview_profile_token": "main",
            "detection_profile_token": "main",
            "recording_uri": uri,
            "preview_uri": uri,
            "detection_uri": uri,
        }
    )


def _media() -> dict:
    return {
        "video_codec": "h264",
        "video_profile": "High",
        "width": 1920,
        "height": 1080,
        "fps_num": 20,
        "fps_den": 1,
        "pixel_format": "yuv420p",
        "has_b_frames": 0,
        "video_time_base": "1/90000",
        "audio_codec": None,
        "audio_profile": None,
        "sample_rate": None,
        "channels": None,
        "audio_frame_samples": None,
    }


def test_onvif_update_uses_coordinator_instead_of_direct_runtime_managers(monkeypatch) -> None:
    spy = _CoordinatorSpy()
    legacy_calls: list[str] = []
    discovered = _discovered("10.0.0.70")

    async def validated(payload, db):
        del db
        result = _discovered(payload.host)
        return result, _media(), result.profiles[0], payload.host, 554, "/main", None

    async def no_schedule_reconcile() -> None:
        return None

    async def legacy_motion(camera_id: int) -> None:
        legacy_calls.append(f"motion:{camera_id}")

    monkeypatch.setattr(onvif_api, "_validated_discovery", validated)
    monkeypatch.setattr(onvif_api, "camera_runtime_coordinator", spy, raising=False)
    monkeypatch.setattr(onvif_api.recording_schedule_manager, "reconcile", no_schedule_reconcile)
    monkeypatch.setattr(onvif_api.motion_detection_manager, "restart_camera", legacy_motion)
    monkeypatch.setattr(onvif_api.recorder_manager, "is_running", lambda _camera_id: False)

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras/onvif",
            json={
                "name": f"runtime-coordinator-onvif-{uuid.uuid4().hex[:8]}",
                "host": "10.0.0.70",
                "port": 80,
                "username": "admin",
                "password": "secret",
                "enabled": False,
                "auto_record": False,
                "timestamp_mode": "native",
            },
        )
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        assert discovered.recording_uri.endswith("/main")

        updated = client.put(
            f"/api/cameras/onvif/{camera_id}",
            json={
                "host": "10.0.0.71",
                "port": 80,
                "username": "admin",
                "password": "secret",
                "enabled": False,
                "auto_record": False,
                "timestamp_mode": "native",
            },
        )
        assert updated.status_code == 200, updated.text

    assert spy.reload_calls == [(camera_id, False)]
    assert legacy_calls == []
