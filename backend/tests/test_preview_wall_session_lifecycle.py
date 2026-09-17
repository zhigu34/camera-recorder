from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.api import preview_wall as preview_wall_api
from app.services import preview_wall as preview_wall_service


class _FakeStdout:
    def __init__(self) -> None:
        self.release_read = asyncio.Event()

    async def read(self, _size: int) -> bytes:
        await self.release_read.wait()
        return b""


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = _FakeStdout()
        self.returncode: int | None = None
        self.started = asyncio.Event()
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
async def test_wall_preview_session_external_close_is_idempotent(monkeypatch) -> None:
    session_type = getattr(preview_wall_service, "WallPreviewSession")
    source = preview_wall_service.WallPreviewSource(
        ip="192.0.2.10",
        port=554,
        username="user",
        password="pass",
        rtsp_path="/sub",
        rtsp_timeout_us=5_000_000,
        fps=3,
        width=480,
    )
    process = _FakeProcess()

    async def fake_spawn(*_args, **_kwargs):
        process.started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    session = session_type(source)

    async def on_frame(_frame: bytes) -> None:
        return None

    streaming = asyncio.create_task(session.stream(on_frame))
    await process.started.wait()
    await session.close()
    await session.close()
    process.stdout.release_read.set()
    await streaming

    assert process.terminate_calls == 1
    assert process.kill_calls == 0


class _FakeSession:
    def __init__(self, cameras: dict[int, SimpleNamespace]) -> None:
        self.cameras = cameras

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, _model, camera_id: int):
        return self.cameras.get(camera_id)


class _TrackingRegistry:
    def __init__(self) -> None:
        self._next = 0
        self._sessions: dict[int, dict[str, object]] = {}
        self.ready = asyncio.Event()
        self.unregistered: list[tuple[int, str]] = []

    async def register(self, camera_id: int, closer) -> str:
        self._next += 1
        session_id = f"session-{self._next}"
        self._sessions.setdefault(camera_id, {})[session_id] = closer
        if sum(len(items) for items in self._sessions.values()) >= 2:
            self.ready.set()
        return session_id

    async def unregister(self, camera_id: int, session_id: str) -> None:
        self.unregistered.append((camera_id, session_id))
        sessions = self._sessions.get(camera_id)
        if not sessions:
            return
        sessions.pop(session_id, None)
        if not sessions:
            self._sessions.pop(camera_id, None)

    async def stop_camera(self, camera_id: int) -> None:
        sessions = self._sessions.pop(camera_id, {})
        for closer in sessions.values():
            await closer()


class _FakeWallSession:
    instances: dict[str, "_FakeWallSession"] = {}

    def __init__(self, source) -> None:
        self.source = source
        self.closed = False
        self._released = asyncio.Event()
        self.instances[source.ip] = self

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._released.set()

    async def stream(self, _on_frame) -> None:
        try:
            await self._released.wait()
        finally:
            await self.close()


class _FakeWebSocket:
    def __init__(self, registry: _TrackingRegistry) -> None:
        self.registry = registry
        self.close_calls = 0
        self.sent_json: list[dict] = []
        self.target_closed_when_stopped: bool | None = None
        self.other_closed_when_stopped: bool | None = None

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> dict:
        return {
            "fps": 3,
            "width": 480,
            "slots": [
                {"index": 0, "camera_id": 10, "stream": "main"},
                {"index": 1, "camera_id": 11, "stream": "main"},
            ],
        }

    async def receive(self) -> dict:
        await asyncio.wait_for(self.registry.ready.wait(), timeout=0.25)
        await self.registry.stop_camera(10)
        self.target_closed_when_stopped = _FakeWallSession.instances["192.0.2.10"].closed
        self.other_closed_when_stopped = _FakeWallSession.instances["192.0.2.11"].closed
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload: dict) -> None:
        self.sent_json.append(payload)

    async def send_bytes(self, _payload: bytes) -> None:
        return None

    async def close(self, *, code: int) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_preview_wall_slots_are_camera_scoped_without_closing_websocket(monkeypatch) -> None:
    cameras = {
        10: SimpleNamespace(
            id=10,
            enabled=True,
            ip="192.0.2.10",
            rtsp_port=554,
            username="user",
            password_encrypted="secret",
            rtsp_path="/main",
            sub_rtsp_path="/sub",
        ),
        11: SimpleNamespace(
            id=11,
            enabled=True,
            ip="192.0.2.11",
            rtsp_port=554,
            username="user",
            password_encrypted="secret",
            rtsp_path="/main",
            sub_rtsp_path="/sub",
        ),
    }
    registry = _TrackingRegistry()
    websocket = _FakeWebSocket(registry)
    _FakeWallSession.instances = {}

    async def fake_runtime(_db):
        return SimpleNamespace(rtsp_timeout_us=5_000_000)

    async def legacy_stream(_source, _on_frame) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(preview_wall_api, "SessionLocal", lambda: _FakeSession(cameras))
    monkeypatch.setattr(preview_wall_api, "load_runtime_settings", fake_runtime)
    monkeypatch.setattr(preview_wall_api, "decrypt_secret", lambda _value: "pass")
    monkeypatch.setattr(preview_wall_api, "stream_preview_frames", legacy_stream)
    monkeypatch.setattr(preview_wall_api, "WallPreviewSession", _FakeWallSession, raising=False)
    monkeypatch.setattr(
        preview_wall_api,
        "camera_media_session_registry",
        registry,
        raising=False,
    )

    await preview_wall_api.preview_wall(websocket)

    assert websocket.target_closed_when_stopped is True
    assert websocket.other_closed_when_stopped is False
    assert websocket.close_calls == 0
