from types import SimpleNamespace

import pytest

from app.core.security import encrypt_secret
from app.services.hik_media_proxy import build_hik_target, iter_hik_stream


def camera() -> SimpleNamespace:
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
    )


def test_build_hik_target_selects_independent_main_and_sub_streams() -> None:
    main = build_hik_target(camera(), "main")
    sub = build_hik_target(camera(), "sub")

    assert (main.host, main.port, main.channel, main.stream_type) == ("10.0.0.8", 8000, 2, 0)
    assert sub.stream_type == 1
    assert main.password == "secret"
    assert "secret" not in repr(main)


class FakeBridgeClient:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    async def iter_media(self, stream_id: str):
        assert stream_id == "stream-1"
        yield b"header"
        yield b"payload"

    async def stop_stream(self, stream_id: str) -> None:
        self.stopped.append(stream_id)


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
