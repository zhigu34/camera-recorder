from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import hik_media as hik_media_api
from app.services import hik_media_proxy


class _FakeDb:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, _model, camera_id: int):
        return SimpleNamespace(id=camera_id)


class _FakeBridgeClient:
    def __init__(self) -> None:
        self.created: list[object] = []
        self.stopped: list[str] = []

    async def create_stream(self, target) -> str:
        self.created.append(target)
        return "stream-1"

    async def iter_media(self, stream_id: str):
        assert stream_id == "stream-1"
        yield b""
        yield b"payload"

    async def stop_stream(self, stream_id: str) -> None:
        self.stopped.append(stream_id)


class _TrackingRegistry:
    def __init__(self) -> None:
        self.registered_camera_ids: list[int] = []
        self.closer = None
        self.unregistered: list[tuple[int, str]] = []

    async def register(self, camera_id: int, closer) -> str:
        self.registered_camera_ids.append(camera_id)
        self.closer = closer
        return "registry-1"

    async def unregister(self, camera_id: int, session_id: str) -> None:
        self.unregistered.append((camera_id, session_id))


@pytest.mark.asyncio
async def test_hik_route_registers_camera_stream_and_external_close(monkeypatch) -> None:
    client = _FakeBridgeClient()
    registry = _TrackingRegistry()
    target = object()

    async def available(_adapter: str) -> None:
        return None

    monkeypatch.setattr(hik_media_api, "SessionLocal", _FakeDb)
    monkeypatch.setattr(hik_media_api, "build_hik_target", lambda _camera, _role: target)
    monkeypatch.setattr(hik_media_api, "HikBridgeClient", lambda: client)
    monkeypatch.setattr(
        hik_media_api,
        "require_camera_adapter_available",
        available,
        raising=False,
    )
    monkeypatch.setattr(
        hik_media_api,
        "camera_media_session_registry",
        registry,
        raising=False,
    )

    response = await hik_media_api.hik_media(42, "main")

    assert client.created == [target]
    assert registry.registered_camera_ids == [42]
    assert registry.closer is not None
    assert await anext(response.body_iterator) == b"payload"

    await registry.closer()
    assert client.stopped == ["stream-1"]

    await response.body_iterator.aclose()
    assert registry.unregistered == [(42, "registry-1")]
    assert client.stopped == ["stream-1"]


@pytest.mark.asyncio
async def test_disabled_hik_media_returns_503_without_stream_creation(monkeypatch) -> None:
    from app.services import camera_adapter_registry as adapter_registry

    client = _FakeBridgeClient()
    monkeypatch.setattr(adapter_registry.settings, "hik_enabled", False)
    monkeypatch.setattr(hik_media_api, "SessionLocal", _FakeDb)
    monkeypatch.setattr(hik_media_api, "build_hik_target", lambda _camera, _role: object())
    monkeypatch.setattr(hik_media_api, "HikBridgeClient", lambda: client)

    with pytest.raises(HTTPException) as exc_info:
        await hik_media_api.hik_media(42, "main")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == adapter_registry.HIK_DISABLED_REASON
    assert client.created == []


@pytest.mark.asyncio
async def test_hik_registered_stream_close_is_idempotent() -> None:
    stream_type = getattr(hik_media_proxy, "HikRegisteredStream")
    client = _FakeBridgeClient()
    stream = stream_type(client, "stream-1")

    await stream.close()
    await stream.close()

    assert client.stopped == ["stream-1"]


@pytest.mark.asyncio
async def test_hik_registered_stream_external_close_and_iterator_finalizer_share_cleanup() -> None:
    stream_type = getattr(hik_media_proxy, "HikRegisteredStream")
    client = _FakeBridgeClient()
    stream = stream_type(client, "stream-1")
    iterator = stream.iter_bytes()

    assert await anext(iterator) == b"payload"
    await stream.close()
    await iterator.aclose()

    assert client.stopped == ["stream-1"]
