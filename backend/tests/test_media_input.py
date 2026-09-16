import pytest

from app.services.hik_media_adapter import HikBridgeTarget
from app.services.media_input import open_media_input
from app.services.media_source import MediaSource


class FakeBridgeClient:
    def __init__(self):
        self.created = []
        self.stopped = []

    async def create_stream(self, target):
        self.created.append(target)
        return "opaque-123"

    def media_url(self, stream_id):
        return f"http://hik-bridge:8100/streams/{stream_id}/media"

    async def stop_stream(self, stream_id):
        self.stopped.append(stream_id)


@pytest.mark.asyncio
async def test_rtsp_media_input_preserves_tcp_and_timeout_without_cleanup() -> None:
    source = MediaSource(
        adapter="manual_rtsp",
        transport="rtsp",
        role="main",
        purpose="recording",
        uri="rtsp://camera/main",
    )
    lease = await open_media_input(source, rtsp_timeout_us=5_000_000)
    assert lease.input.transport_args == (
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "5000000",
    )
    assert lease.input.uri == "rtsp://camera/main"
    await lease.close()
    await lease.close()


@pytest.mark.asyncio
async def test_hik_media_input_creates_opaque_bridge_session_and_closes_once() -> None:
    target = HikBridgeTarget("10.0.0.8", 8000, "admin", "secret", 2, 0)
    source = MediaSource(
        adapter="hik_sdk",
        transport="hik_bridge",
        role="main",
        purpose="recording",
        bridge_target=target,
    )
    bridge = FakeBridgeClient()
    lease = await open_media_input(
        source,
        rtsp_timeout_us=7_000_000,
        bridge_client=bridge,
    )
    assert bridge.created == [target]
    assert lease.input.transport_args == ("-rw_timeout", "7000000")
    assert lease.input.uri == "http://hik-bridge:8100/streams/opaque-123/media"
    assert "secret" not in repr(lease.input)
    await lease.close()
    await lease.close()
    assert bridge.stopped == ["opaque-123"]
