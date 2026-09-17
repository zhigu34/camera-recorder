from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import cameras as cameras_api
from app.main import app
from app.services.camera_preview import PreviewSession


class _Stdout:
    async def read(self, _size: int) -> bytes:
        return b""


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.stdout = _Stdout()
        self.terminate_calls = 0
        self.kill_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.mark.asyncio
async def test_preview_session_close_is_idempotent() -> None:
    process = _FakeProcess()
    session = PreviewSession(process=process, first_chunk=b"frame")

    await session.close()
    await session.close()

    assert process.terminate_calls == 1
    assert process.kill_calls == 0


@pytest.mark.asyncio
async def test_preview_stream_finalizer_is_safe_after_external_close() -> None:
    process = _FakeProcess()
    session = PreviewSession(process=process, first_chunk=b"frame")

    await session.close()
    chunks = [chunk async for chunk in session.stream()]

    assert chunks == [b"frame"]
    assert process.terminate_calls == 1


class _EndpointPreviewSession:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1

    async def stream(self):
        try:
            yield b"--ffmpeg\r\nContent-Type: image/jpeg\r\n\r\nx\r\n"
        finally:
            await self.close()


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered: list[tuple[int, object]] = []
        self.unregistered: list[tuple[int, str]] = []

    async def register(self, camera_id: int, closer) -> str:
        self.registered.append((camera_id, closer))
        return "session-1"

    async def unregister(self, camera_id: int, session_id: str) -> None:
        self.unregistered.append((camera_id, session_id))


def _camera_payload() -> dict:
    return {
        "name": f"preview-lifecycle-{uuid.uuid4().hex[:10]}",
        "ip": "192.0.2.91",
        "rtsp_port": 554,
        "username": "admin",
        "password": "secret",
        "rtsp_path": "/main",
        "enabled": True,
        "auto_record": False,
        "timestamp_mode": "native",
    }


def test_preview_endpoint_registers_and_unregisters_active_session(monkeypatch) -> None:
    preview_session = _EndpointPreviewSession()
    registry = _FakeRegistry()

    async def fake_open_preview(**_kwargs):
        return preview_session

    monkeypatch.setattr(cameras_api, "open_mjpeg_preview", fake_open_preview)
    monkeypatch.setattr(
        cameras_api,
        "camera_media_session_registry",
        registry,
        raising=False,
    )

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_camera_payload())
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])

        response = client.get(f"/api/cameras/{camera_id}/preview.mjpeg?stream=main")

    assert response.status_code == 200, response.text
    assert response.headers["X-Preview-Stream"] == "main"
    assert response.content
    assert len(registry.registered) == 1
    assert registry.registered[0][0] == camera_id
    assert registry.unregistered == [(camera_id, "session-1")]
