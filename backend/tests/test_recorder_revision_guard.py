from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import recorder_manager as recorder_module
from app.services.ffmpeg_builder import CameraRuntimeConfig
from app.services.recorder_manager import CameraWorker


class _SessionContext:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _EmptyStderr:
    async def readline(self) -> bytes:
        return b""


class _FakeProcess:
    def __init__(self, worker: CameraWorker, *, stop_worker: bool, return_code: int = 1) -> None:
        self.worker = worker
        self.stop_worker = stop_worker
        self.return_code = return_code
        self.returncode = None
        self.stderr = _EmptyStderr()
        self.pid = 1234

    async def wait(self) -> int:
        if self.stop_worker:
            self.worker.stop_requested = True
        self.returncode = self.return_code
        return self.return_code


def _config(*, revision: int | None = 7) -> CameraRuntimeConfig:
    return CameraRuntimeConfig(
        id=21,
        name="Front Door",
        stream_uri="rtsp://camera/main",
        timestamp_mode="wallclock",
        fps_num=25,
        fps_den=1,
        audio_codec=None,
        sample_rate=None,
        audio_frame_samples=None,
        connection_revision=revision,
    )


def _stub_worker_runtime(monkeypatch, worker: CameraWorker) -> list[_FakeProcess]:
    processes: list[_FakeProcess] = []
    monkeypatch.setattr(recorder_module, "SessionLocal", lambda: _SessionContext())

    async def load_runtime(_session):
        return SimpleNamespace()

    monkeypatch.setattr(recorder_module, "load_runtime_settings", load_runtime)
    monkeypatch.setattr(recorder_module, "build_record_command", lambda *_args, **_kwargs: ["ffmpeg"])

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(worker, "_log", no_op)
    monkeypatch.setattr(worker, "_record_camera_event", no_op)
    monkeypatch.setattr(worker, "_mark_disconnected", no_op)
    monkeypatch.setattr(worker, "_check_failure_streak", no_op)
    monkeypatch.setattr(worker, "_start_recovery_confirmation", lambda _process: None)
    monkeypatch.setattr(worker, "_start_stability_confirmation", lambda _process: None)

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(recorder_module.asyncio, "sleep", no_sleep)
    return processes


@pytest.mark.asyncio
async def test_stale_revision_exits_before_first_ffmpeg_spawn(monkeypatch) -> None:
    worker = CameraWorker(_config(revision=7))
    processes = _stub_worker_runtime(monkeypatch, worker)
    checks: list[tuple[int, int | None]] = []

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return "stale"

    monkeypatch.setattr(
        recorder_module,
        "connection_revision_state",
        revision_state,
        raising=False,
    )

    async def spawn(*_args, **_kwargs):
        process = _FakeProcess(worker, stop_worker=True)
        processes.append(process)
        return process

    monkeypatch.setattr(recorder_module.asyncio, "create_subprocess_exec", spawn)

    await worker._run_loop()

    assert checks == [(21, 7)]
    assert processes == []
    assert worker.restart_count == 0
    assert worker.consecutive_failure_count == 0
    assert worker.last_failure_at is None
    assert worker.state == "STOPPED"


@pytest.mark.asyncio
async def test_stale_revision_prevents_second_spawn_after_reconnect(monkeypatch) -> None:
    worker = CameraWorker(_config(revision=7))
    processes = _stub_worker_runtime(monkeypatch, worker)
    states = iter(("current", "stale"))
    checks: list[tuple[int, int | None]] = []

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return next(states)

    monkeypatch.setattr(
        recorder_module,
        "connection_revision_state",
        revision_state,
        raising=False,
    )

    async def spawn(*_args, **_kwargs):
        process = _FakeProcess(worker, stop_worker=len(processes) >= 1)
        processes.append(process)
        return process

    monkeypatch.setattr(recorder_module.asyncio, "create_subprocess_exec", spawn)

    await worker._run_loop()

    assert checks == [(21, 7), (21, 7)]
    assert len(processes) == 1
    assert worker.restart_count == 1
    assert worker.consecutive_failure_count == 1
    assert worker.state == "STOPPED"


@pytest.mark.asyncio
async def test_none_revision_keeps_legacy_recorder_behavior(monkeypatch) -> None:
    worker = CameraWorker(_config(revision=None))
    processes = _stub_worker_runtime(monkeypatch, worker)
    checks: list[tuple[int, int | None]] = []

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return "current"

    monkeypatch.setattr(
        recorder_module,
        "connection_revision_state",
        revision_state,
        raising=False,
    )

    async def spawn(*_args, **_kwargs):
        process = _FakeProcess(worker, stop_worker=True, return_code=0)
        processes.append(process)
        return process

    monkeypatch.setattr(recorder_module.asyncio, "create_subprocess_exec", spawn)

    await worker._run_loop()

    assert checks == [(21, None)]
    assert len(processes) == 1
    assert worker.restart_count == 0
    assert worker.consecutive_failure_count == 0
    assert worker.state == "STOPPED"
