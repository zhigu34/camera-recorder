import json

import httpx
import pytest

from app.services.hik_bridge_client import HikBridgeClient, HikBridgeClientError
from app.services.hik_media_adapter import HikBridgeTarget


@pytest.mark.asyncio
async def test_create_stream_sends_credentials_but_returns_only_opaque_media_url() -> None:
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={"stream_id": "opaque-id"})

    client = HikBridgeClient(
        "http://hik-bridge:8100",
        transport=httpx.MockTransport(handler),
    )
    target = HikBridgeTarget("10.0.0.8", 8000, "admin", "secret", 2, 1)
    stream_id = await client.create_stream(target)
    assert stream_id == "opaque-id"
    assert seen == {
        "host": "10.0.0.8",
        "port": 8000,
        "username": "admin",
        "password": "secret",
        "channel": 2,
        "stream_type": 1,
    }
    media_url = client.media_url(stream_id)
    assert media_url == "http://hik-bridge:8100/streams/opaque-id/media"
    assert "secret" not in media_url and "admin" not in media_url


@pytest.mark.asyncio
async def test_bridge_error_redacts_password() -> None:
    def handler(request: httpx.Request):
        return httpx.Response(503, json={"detail": "login failed for password secret"})

    client = HikBridgeClient(
        "http://hik-bridge:8100",
        transport=httpx.MockTransport(handler),
    )
    target = HikBridgeTarget("10.0.0.8", 8000, "admin", "secret", 1, 0)
    with pytest.raises(HikBridgeClientError) as exc:
        await client.create_stream(target)
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_stop_stream_uses_opaque_id_only() -> None:
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        return httpx.Response(204)

    client = HikBridgeClient(
        "http://hik-bridge:8100",
        transport=httpx.MockTransport(handler),
    )
    await client.stop_stream("opaque-id")
    assert calls == [("DELETE", "/streams/opaque-id")]


@pytest.mark.asyncio
async def test_health_reads_bridge_health_endpoint() -> None:
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "ok", "sdk": "loaded"})

    client = HikBridgeClient(
        "http://hik-bridge:8100",
        transport=httpx.MockTransport(handler),
    )

    assert await client.health() == {"status": "ok", "sdk": "loaded"}
    assert calls == [("GET", "/health")]
