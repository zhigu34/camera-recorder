from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.api import cameras as cameras_api
from app.main import app


def _camera_payload(*, enabled: bool) -> dict:
    return {
        "name": f"runtime-enabled-guard-{uuid.uuid4().hex[:10]}",
        "ip": "192.0.2.80",
        "rtsp_port": 554,
        "username": "admin",
        "password": "secret",
        "rtsp_path": "/main",
        "enabled": enabled,
        "auto_record": False,
        "timestamp_mode": "native",
    }


class _PreviewSession:
    async def stream(self):
        yield b"--ffmpeg\r\nContent-Type: image/jpeg\r\n\r\nx\r\n"


def test_disabled_camera_rejects_start_restart_and_preview_but_allows_probe(monkeypatch) -> None:
    device_calls: list[str] = []

    async def fake_start(camera):
        device_calls.append(f"start:{camera.id}")
        return {"camera_id": camera.id, "state": "RECORDING", "pid": 1}

    async def fake_restart(camera):
        device_calls.append(f"restart:{camera.id}")
        return {"camera_id": camera.id, "state": "RECORDING", "pid": 1}

    async def fake_preview(**_kwargs):
        device_calls.append("preview")
        return _PreviewSession()

    async def fake_probe(camera, *, rtsp_timeout_us: int):
        assert rtsp_timeout_us > 0
        device_calls.append(f"probe:{camera.id}")
        return {"ok": True}

    monkeypatch.setattr(cameras_api.recorder_manager, "start", fake_start)
    monkeypatch.setattr(cameras_api.recorder_manager, "restart", fake_restart)
    monkeypatch.setattr(cameras_api, "open_mjpeg_preview", fake_preview)
    monkeypatch.setattr(cameras_api, "probe_camera_media", fake_probe)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_camera_payload(enabled=False))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])

        started = client.post(f"/api/cameras/{camera_id}/start")
        assert started.status_code == 409, started.text
        assert started.json()["detail"] == "camera is disabled"

        restarted = client.post(f"/api/cameras/{camera_id}/restart")
        assert restarted.status_code == 409, restarted.text
        assert restarted.json()["detail"] == "camera is disabled"

        previewed = client.get(f"/api/cameras/{camera_id}/preview.mjpeg")
        assert previewed.status_code == 409, previewed.text
        assert previewed.json()["detail"] == "camera is disabled"

        probed = client.post(f"/api/cameras/{camera_id}/probe")
        assert probed.status_code == 200, probed.text
        assert probed.json()["ok"] is True

    assert device_calls == [f"probe:{camera_id}"]


def test_enabled_manual_start_uses_event_buffer_handoff_entrypoint(monkeypatch) -> None:
    handoff_calls: list[int] = []

    async def handoff_start(camera):
        handoff_calls.append(int(camera.id))
        return {"camera_id": int(camera.id), "state": "RECORDING", "pid": 1}

    async def forbidden_direct_start(_camera):
        raise AssertionError("camera start endpoint bypassed start_regular_recorder")

    monkeypatch.setattr(cameras_api, "start_regular_recorder", handoff_start, raising=False)
    monkeypatch.setattr(cameras_api.recorder_manager, "start", forbidden_direct_start)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_camera_payload(enabled=True))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])

        started = client.post(f"/api/cameras/{camera_id}/start")
        assert started.status_code == 200, started.text
        assert started.json()["state"] == "RECORDING"

    assert handoff_calls == [camera_id]
