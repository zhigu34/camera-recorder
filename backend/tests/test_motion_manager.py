import asyncio
from datetime import datetime, timezone

import pytest

from app.services.motion_manager import MotionDetectionManager
from app.services.motion_worker import MotionWorkerConfig


def _config(camera_id: int) -> MotionWorkerConfig:
    return MotionWorkerConfig(
        camera_id=camera_id,
        ip="192.0.2.30",
        port=554,
        username="admin",
        password="secret",
        main_path="/ch1/main",
        sub_path="/ch1/sub",
        rtsp_timeout_us=5_000_000,
        analysis_fps=5,
        analysis_width=640,
        sensitivity="medium",
        min_duration_ms=800,
        merge_gap_ms=3000,
        zones=[],
    )


class FakeWorker:
    created: list["FakeWorker"] = []

    def __init__(self, config, *, on_event, on_status):
        self.config = config
        self.on_event = on_event
        self.on_status = on_status
        self.cancelled = False
        FakeWorker.created.append(self)

    async def run(self) -> None:
        self.on_status("running", "sub", datetime.now(timezone.utc), None)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_manager_starts_restarts_and_stops_one_worker_per_camera() -> None:
    FakeWorker.created.clear()
    enabled = {1: True}

    async def enabled_loader() -> list[int]:
        return [camera_id for camera_id, value in enabled.items() if value]

    async def config_loader(camera_id: int):
        return _config(camera_id) if enabled.get(camera_id) else None

    async def event_sink(camera_id, event, frame) -> None:
        return None

    manager = MotionDetectionManager(
        enabled_camera_loader=enabled_loader,
        config_loader=config_loader,
        event_sink=event_sink,
        worker_factory=FakeWorker,
        reconnect_delays=(0.01,),
    )

    await manager.start()
    await asyncio.sleep(0)
    assert manager.active_camera_ids() == [1]
    assert manager.status(1)["state"] == "running"
    assert manager.status(1)["stream"] == "sub"
    assert len(FakeWorker.created) == 1

    first = FakeWorker.created[0]
    await manager.restart_camera(1)
    await asyncio.sleep(0)
    assert first.cancelled is True
    assert len(FakeWorker.created) == 2
    assert manager.active_camera_ids() == [1]

    enabled[1] = False
    await manager.restart_camera(1)
    assert FakeWorker.created[-1].cancelled is True
    assert manager.active_camera_ids() == []
    assert manager.status(1)["state"] == "disabled"

    await manager.stop()


@pytest.mark.asyncio
async def test_manager_supervisor_reconnects_after_worker_failure() -> None:
    calls = 0

    class FailThenWaitWorker(FakeWorker):
        async def run(self) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("stream failed")
            self.on_status("running", "sub", datetime.now(timezone.utc), None)
            await asyncio.Event().wait()

    async def enabled_loader() -> list[int]:
        return [2]

    async def config_loader(camera_id: int):
        return _config(camera_id)

    async def event_sink(camera_id, event, frame) -> None:
        return None

    manager = MotionDetectionManager(
        enabled_camera_loader=enabled_loader,
        config_loader=config_loader,
        event_sink=event_sink,
        worker_factory=FailThenWaitWorker,
        reconnect_delays=(0.001,),
    )
    await manager.start()
    for _ in range(20):
        if calls >= 2 and manager.status(2)["state"] == "running":
            break
        await asyncio.sleep(0.002)

    assert calls >= 2
    assert manager.status(2)["state"] == "running"
    await manager.stop()
