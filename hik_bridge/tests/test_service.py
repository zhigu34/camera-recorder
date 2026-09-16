import asyncio

import pytest

from hik_bridge.service import HikBridgeError, HikBridgeService, StreamRequest


class FakeSdk:
    def __init__(self):
        self.runtime_available = True
        self.initialized = 0
        self.cleaned = 0
        self.logins = []
        self.logouts = []
        self.previews = []
        self.stopped = []
        self.callback = None

    def initialize(self):
        self.initialized += 1

    def cleanup(self):
        self.cleaned += 1

    def login(self, host, port, username, password):
        self.logins.append((host, port, username, password))
        if password == "bad":
            raise HikBridgeError("SDK login failed", code=1)
        return 7, {"serial_number": "SER123", "device_type": 42}

    def logout(self, user_id):
        self.logouts.append(user_id)

    def start_realplay(self, user_id, channel, stream_type, callback):
        self.previews.append((user_id, channel, stream_type))
        self.callback = callback
        return 9

    def stop_realplay(self, handle):
        self.stopped.append(handle)


class ImmediateCallbackSdk(FakeSdk):
    def start_realplay(self, user_id, channel, stream_type, callback):
        handle = super().start_realplay(user_id, channel, stream_type, callback)
        callback(b"system-head-before-return")
        return handle


@pytest.mark.asyncio
async def test_probe_balances_login_logout_and_hides_password():
    sdk = FakeSdk()
    service = HikBridgeService(sdk)
    await service.start()
    result = await service.probe("10.0.0.8", 8000, "admin", "secret")
    assert result["serial_number"] == "SER123"
    assert sdk.logins == [("10.0.0.8", 8000, "admin", "secret")]
    assert sdk.logouts == [7]
    assert "secret" not in repr(result)
    await service.stop()
    assert sdk.initialized == 1 and sdk.cleaned == 1


@pytest.mark.asyncio
async def test_stream_uses_channel_and_stream_type_and_preserves_callback_order():
    sdk = FakeSdk()
    service = HikBridgeService(sdk, queue_size=4)
    await service.start()
    stream_id = await service.create_stream(
        StreamRequest("10.0.0.8", 8000, "admin", "secret", 2, 1)
    )
    assert sdk.previews == [(7, 2, 1)]
    sdk.callback(b"head")
    sdk.callback(b"packet-1")
    sdk.callback(b"packet-2")
    chunks = []
    async for chunk in service.iter_stream(stream_id):
        chunks.append(chunk)
        if len(chunks) == 3:
            break
    assert chunks == [b"head", b"packet-1", b"packet-2"]
    await service.stop_stream(stream_id)
    assert sdk.stopped == [9]
    assert sdk.logouts == [7]
    await service.stop()


@pytest.mark.asyncio
async def test_stream_keeps_callback_bytes_emitted_before_realplay_returns():
    sdk = ImmediateCallbackSdk()
    service = HikBridgeService(sdk, queue_size=4)
    await service.start()
    stream_id = await service.create_stream(
        StreamRequest("10.0.0.8", 8000, "admin", "secret", 1, 0)
    )
    iterator = service.iter_stream(stream_id)

    assert await asyncio.wait_for(anext(iterator), timeout=1.0) == b"system-head-before-return"

    await iterator.aclose()
    assert sdk.stopped == [9]
    assert sdk.logouts == [7]
    await service.stop()


@pytest.mark.asyncio
async def test_stream_queue_is_bounded_and_overflow_closes_session():
    sdk = FakeSdk()
    service = HikBridgeService(sdk, queue_size=2)
    await service.start()
    stream_id = await service.create_stream(
        StreamRequest("10.0.0.8", 8000, "admin", "secret", 1, 0)
    )
    sdk.callback(b"1")
    sdk.callback(b"2")
    sdk.callback(b"3")
    chunks = []
    async for chunk in service.iter_stream(stream_id):
        chunks.append(chunk)
    assert chunks in ([b"1", b"2"], [b"1"])
    assert sdk.stopped == [9]
    await service.stop()


@pytest.mark.asyncio
async def test_stop_stream_is_idempotent():
    sdk = FakeSdk()
    service = HikBridgeService(sdk)
    await service.start()
    stream_id = await service.create_stream(
        StreamRequest("10.0.0.8", 8000, "admin", "secret", 1, 0)
    )
    await service.stop_stream(stream_id)
    await service.stop_stream(stream_id)
    assert sdk.stopped == [9]
    assert sdk.logouts == [7]
    await service.stop()


@pytest.mark.asyncio
async def test_stop_stream_unblocks_idle_media_iterator():
    sdk = FakeSdk()
    service = HikBridgeService(sdk)
    await service.start()
    stream_id = await service.create_stream(
        StreamRequest("10.0.0.8", 8000, "admin", "secret", 1, 0)
    )
    iterator = service.iter_stream(stream_id)
    waiting = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)

    await service.stop_stream(stream_id)

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, timeout=1.0)
    assert sdk.stopped == [9]
    assert sdk.logouts == [7]
    await service.stop()
