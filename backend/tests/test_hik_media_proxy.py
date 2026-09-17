from types import SimpleNamespace

import pytest

from app.core.security import encrypt_secret
from app.services.hik_media_proxy import build_hik_target, iter_hik_stream


def legacy_camera() -> SimpleNamespace:
    return SimpleNamespace(
        connection_type="hik_sdk",
        ip="10.0.0.8",
        username="admin",
        password_encrypted=encrypt_secret("secret"),
        hik_metadata=SimpleNamespace(
            sdk_port=8000,
            channel=2,
            main_stream_type=0,
            sub_stream_type=1,
        ),
        connection=None,
    )


def canonical_camera(**connection_overrides) -> SimpleNamespace:
    connection_values = {
        "adapter": "hik_sdk",
        "host": "10.0.0.9",
        "username": "current-admin",
        "password_encrypted": encrypt_secret("current-secret"),
        "hik_config": SimpleNamespace(
            sdk_port=9000,
            channel=4,
            main_stream_type=2,
            sub_stream_type=3,
        ),
    }
    connection_values.update(connection_overrides)
    return SimpleNamespace(
        connection_type="manual_rtsp",
        ip="10.0.0.8",
        username="legacy-admin",
        password_encrypted=encrypt_secret("legacy-secret"),
        hik_metadata=SimpleNamespace(
            sdk_port=8000,
            channel=2,
            main_stream_type=0,
            sub_stream_type=1,
        ),
        connection=SimpleNamespace(**connection_values),
    )


def test_build_hik_target_legacy_fallback_selects_independent_main_and_sub_streams() -> None:
    main = build_hik_target(legacy_camera(), "main")
    sub = build_hik_target(legacy_camera(), "sub")

    assert (main.host, main.port, main.channel, main.stream_type) == ("10.0.0.8", 8000, 2, 0)
    assert sub.stream_type == 1
    assert main.password == "secret"
    assert "secret" not in repr(main)


def test_build_hik_target_prefers_current_connection_over_legacy_shadow() -> None:
    main = build_hik_target(canonical_camera(), "main")
    sub = build_hik_target(canonical_camera(), "sub")

    assert (main.host, main.port, main.channel, main.stream_type) == ("10.0.0.9", 9000, 4, 2)
    assert main.username == "current-admin"
    assert main.password == "current-secret"
    assert sub.stream_type == 3


def test_current_hik_connection_without_config_does_not_fall_back_to_legacy_metadata() -> None:
    with pytest.raises(ValueError, match="HIK current connection config is missing"):
        build_hik_target(canonical_camera(hik_config=None), "main")


def test_current_non_hik_connection_is_rejected_even_when_legacy_shadow_says_hik() -> None:
    with pytest.raises(ValueError, match="current connection adapter is onvif, expected hik_sdk"):
        build_hik_target(canonical_camera(adapter="onvif"), "main")


class FakeBridgeClient:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    async def iter_media(self, stream_id: str):
        assert stream_id == "stream-1"
        yield b"header"
        yield b"payload"

    async def stop_stream(self, stream_id: str) -> None:
        self.stopped.append(stream_id)


class EmptyChunkBridgeClient(FakeBridgeClient):
    async def iter_media(self, stream_id: str):
        assert stream_id == "stream-1"
        yield b""
        yield b"payload"


class FailingStopBridgeClient(FakeBridgeClient):
    async def stop_stream(self, stream_id: str) -> None:
        self.stopped.append(stream_id)
        raise RuntimeError("sidecar cleanup failed")


@pytest.mark.asyncio
async def test_iter_hik_stream_always_releases_sidecar_session() -> None:
    client = FakeBridgeClient()
    chunks = [chunk async for chunk in iter_hik_stream(client, "stream-1")]

    assert chunks == [b"header", b"payload"]
    assert client.stopped == ["stream-1"]


@pytest.mark.asyncio
async def test_iter_hik_stream_releases_session_when_consumer_closes_early() -> None:
    client = FakeBridgeClient()
    stream = iter_hik_stream(client, "stream-1")
    assert await anext(stream) == b"header"
    await stream.aclose()

    assert client.stopped == ["stream-1"]


@pytest.mark.asyncio
async def test_iter_hik_stream_skips_empty_bridge_chunks() -> None:
    client = EmptyChunkBridgeClient()
    chunks = [chunk async for chunk in iter_hik_stream(client, "stream-1")]

    assert chunks == [b"payload"]
    assert client.stopped == ["stream-1"]


@pytest.mark.asyncio
async def test_iter_hik_stream_does_not_surface_sidecar_cleanup_failure() -> None:
    client = FailingStopBridgeClient()
    chunks = [chunk async for chunk in iter_hik_stream(client, "stream-1")]

    assert chunks == [b"header", b"payload"]
    assert client.stopped == ["stream-1"]
