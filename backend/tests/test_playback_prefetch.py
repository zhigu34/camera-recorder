import time

import pytest

from app.services import playback_prefetch as module
from app.services.playback_prefetch import (
    PlaybackPrefetchManager,
    PlaybackPrefetchMiddleware,
    WarmedDirectLink,
)


def test_prefetch_direct_link_expires():
    manager = PlaybackPrefetchManager()
    now = time.monotonic()
    manager._direct_links[7] = WarmedDirectLink(
        url="https://cdn.example/video.mp4",
        expires_at=now + 60,
        warmed_at=now,
    )
    assert manager.cached_direct_link(7) == "https://cdn.example/video.mp4"

    manager._direct_links[8] = WarmedDirectLink(
        url="https://cdn.example/expired.mp4",
        expires_at=now - 1,
        warmed_at=now - 2,
    )
    assert manager.cached_direct_link(8) is None
    assert 8 not in manager._direct_links


def test_playback_metrics_summarize_latency():
    manager = PlaybackPrefetchManager()
    manager.record_latency("cloud", 100)
    manager.record_latency("cloud", 200)
    manager.record_latency("cloud", 300)
    manager.record_latency("prefetch", 80)

    snapshot = manager.snapshot()

    assert snapshot["backend_response"]["cloud"]["samples"] == 3
    assert snapshot["backend_response"]["cloud"]["avg_ms"] == 200.0
    assert snapshot["backend_response"]["cloud"]["max_ms"] == 300
    assert snapshot["prefetch"]["probe_latency"]["samples"] == 1
    assert snapshot["prefetch"]["probe_latency"]["avg_ms"] == 80.0


@pytest.mark.asyncio
async def test_middleware_uses_warmed_cloud_redirect(monkeypatch):
    manager = PlaybackPrefetchManager()
    now = time.monotonic()
    manager._direct_links[77] = WarmedDirectLink(
        url="https://cdn.example/77.mp4?token=warm",
        expires_at=now + 60,
        warmed_at=now,
    )
    monkeypatch.setattr(module, "playback_prefetch_manager", manager)

    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    middleware = PlaybackPrefetchMiddleware(app)
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/recordings/77/cloud-stream",
            "headers": [],
        },
        receive,
        send,
    )

    assert called is False
    assert messages[0]["status"] == 302
    headers = dict(messages[0]["headers"])
    assert headers[b"location"] == b"https://cdn.example/77.mp4?token=warm"
    assert headers[b"x-playback-prefetch"] == b"hit"
    assert manager.snapshot()["prefetch"]["direct_hits"] == 1


@pytest.mark.asyncio
async def test_middleware_records_first_body_latency(monkeypatch):
    manager = PlaybackPrefetchManager()
    monkeypatch.setattr(module, "playback_prefetch_manager", manager)
    armed = []
    monkeypatch.setattr(manager, "arm", lambda recording_id: armed.append(recording_id))

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"video", "more_body": False})

    middleware = PlaybackPrefetchMiddleware(app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        return None

    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/recordings/12/stream",
            "headers": [],
        },
        receive,
        send,
    )

    assert armed == [12]
    assert manager.snapshot()["backend_response"]["stream"]["samples"] == 1
