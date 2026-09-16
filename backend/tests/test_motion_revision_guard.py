from __future__ import annotations

import pytest

import app.services.motion_manager as motion_manager_module
from app.services.motion_manager import MotionDetectionManager
from app.services.motion_worker import MotionWorkerConfig


def _config(*, revision: int | None = 11) -> MotionWorkerConfig:
    return MotionWorkerConfig(
        camera_id=31,
        ip="192.0.2.31",
        port=554,
        username="admin",
        password="secret",
        main_path="/main",
        sub_path="/sub",
        rtsp_timeout_us=3_000_000,
        analysis_fps=5,
        analysis_width=640,
        sensitivity="medium",
        min_duration_ms=500,
        merge_gap_ms=1000,
        zones=[],
        connection_revision=revision,
    )


async def _event_sink(_camera_id, _event, _frame) -> None:
    return None


@pytest.mark.asyncio
async def test_stale_revision_stops_before_first_motion_worker(monkeypatch) -> None:
    worker_calls: list[int] = []
    checks: list[tuple[int, int | None]] = []

    manager = MotionDetectionManager(
        event_sink=_event_sink,
        worker_factory=lambda *_args, **_kwargs: worker_calls.append(1),
        reconnect_delays=(0.0,),
    )
    manager._running = True

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return "stale"

    monkeypatch.setattr(
        motion_manager_module,
        "connection_revision_state",
        revision_state,
        raising=False,
    )

    await manager._supervise(_config())

    assert checks == [(31, 11)]
    assert worker_calls == []
    assert manager.status(31)["state"] == "stopped"
    assert manager.status(31)["last_error"] is None


@pytest.mark.asyncio
async def test_stale_revision_prevents_motion_reconnect(monkeypatch) -> None:
    checks: list[tuple[int, int | None]] = []
    worker_calls = 0
    states = iter(("current", "stale"))

    class FailWorker:
        def __init__(self, _config, *, on_event, on_status):
            nonlocal worker_calls
            worker_calls += 1
            self.on_event = on_event
            self.on_status = on_status
            self.on_event_started = None

        async def run(self) -> None:
            raise RuntimeError("stream failed")

    manager = MotionDetectionManager(
        event_sink=_event_sink,
        worker_factory=FailWorker,
        reconnect_delays=(0.0,),
    )
    manager._running = True

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return next(states)

    monkeypatch.setattr(
        motion_manager_module,
        "connection_revision_state",
        revision_state,
        raising=False,
    )

    await manager._supervise(_config())

    assert checks == [(31, 11), (31, 11)]
    assert worker_calls == 1
    assert manager.status(31)["state"] == "stopped"
    assert manager.status(31)["last_error"] is None


@pytest.mark.asyncio
async def test_unknown_revision_keeps_motion_worker_path(monkeypatch) -> None:
    checks: list[tuple[int, int | None]] = []
    worker_calls = 0

    class StopWorker:
        def __init__(self, _config, *, on_event, on_status):
            nonlocal worker_calls
            worker_calls += 1
            self.on_event = on_event
            self.on_status = on_status
            self.on_event_started = None

        async def run(self) -> None:
            self.on_status("running", "sub", None, None, None)
            manager._running = False

    manager = MotionDetectionManager(
        event_sink=_event_sink,
        worker_factory=StopWorker,
        reconnect_delays=(0.0,),
    )
    manager._running = True

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return "unknown"

    monkeypatch.setattr(
        motion_manager_module,
        "connection_revision_state",
        revision_state,
        raising=False,
    )

    await manager._supervise(_config())

    assert checks == [(31, 11)]
    assert worker_calls == 1
    assert manager.status(31)["state"] == "running"
    assert manager.status(31)["last_error"] is None
