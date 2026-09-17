import asyncio

import pytest

from app.services.camera_media_session_registry import CameraMediaSessionRegistry


@pytest.mark.asyncio
async def test_stop_camera_closes_only_target_camera_sessions() -> None:
    registry = CameraMediaSessionRegistry()
    calls: list[str] = []

    async def close_a1() -> None:
        calls.append("a1")

    async def close_a2() -> None:
        calls.append("a2")

    async def close_b1() -> None:
        calls.append("b1")

    await registry.register(1, close_a1)
    await registry.register(1, close_a2)
    await registry.register(2, close_b1)

    await registry.stop_camera(1)

    assert calls == ["a1", "a2"]
    assert await registry.active_count(1) == 0
    assert await registry.active_count(2) == 1


@pytest.mark.asyncio
async def test_stop_camera_detaches_before_awaiting_closers() -> None:
    registry = CameraMediaSessionRegistry()
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    calls: list[str] = []

    async def old_close() -> None:
        close_started.set()
        await allow_close.wait()
        calls.append("old")

    await registry.register(7, old_close)
    stopping = asyncio.create_task(registry.stop_camera(7))
    await close_started.wait()

    async def new_close() -> None:
        calls.append("new")

    await registry.register(7, new_close)
    allow_close.set()
    await stopping

    assert calls == ["old"]
    assert await registry.active_count(7) == 1


@pytest.mark.asyncio
async def test_unregister_is_idempotent() -> None:
    registry = CameraMediaSessionRegistry()

    async def closer() -> None:
        return None

    session_id = await registry.register(3, closer)
    await registry.unregister(3, session_id)
    await registry.unregister(3, session_id)

    assert await registry.active_count(3) == 0


@pytest.mark.asyncio
async def test_closer_failure_does_not_block_remaining_sessions() -> None:
    registry = CameraMediaSessionRegistry()
    calls: list[str] = []

    async def failing() -> None:
        calls.append("failing")
        raise RuntimeError("cleanup failed")

    async def succeeding() -> None:
        calls.append("succeeding")

    await registry.register(9, failing)
    await registry.register(9, succeeding)

    await registry.stop_camera(9)

    assert calls == ["failing", "succeeding"]
    assert await registry.active_count(9) == 0


@pytest.mark.asyncio
async def test_stop_all_drains_every_camera() -> None:
    registry = CameraMediaSessionRegistry()
    calls: list[str] = []

    async def close_a() -> None:
        calls.append("a")

    async def close_b() -> None:
        calls.append("b")

    await registry.register(1, close_a)
    await registry.register(2, close_b)

    await registry.stop_all()

    assert calls == ["a", "b"]
    assert await registry.active_count(1) == 0
    assert await registry.active_count(2) == 0
