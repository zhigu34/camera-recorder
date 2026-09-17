from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import event_recording as event_recording_module
from app.services.event_recording import EventBufferWorker, EventRecordingManager


class _FakeProcess:
    def __init__(self, worker: EventBufferWorker, *, stop_worker: bool = False) -> None:
        self.worker = worker
        self.stop_worker = stop_worker
        self.returncode = None

    async def wait(self) -> int:
        if self.stop_worker:
            self.worker._stop.set()
        self.returncode = 1
        return 1


@pytest.mark.asyncio
async def test_stale_revision_stops_event_buffer_before_first_spawn(monkeypatch, tmp_path: Path) -> None:
    worker = EventBufferWorker(
        41,
        "rtsp://camera/main",
        tmp_path,
        3_000_000,
        connection_revision=4,
    )
    checks: list[tuple[int, int | None]] = []
    spawn_calls: list[tuple] = []

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return "stale"

    async def spawn(*args, **kwargs):
        spawn_calls.append((args, kwargs))
        return _FakeProcess(worker, stop_worker=True)

    monkeypatch.setattr(event_recording_module, "connection_revision_state", revision_state, raising=False)
    monkeypatch.setattr(event_recording_module.asyncio, "create_subprocess_exec", spawn)

    await worker._run()

    assert checks == [(41, 4)]
    assert spawn_calls == []


@pytest.mark.asyncio
async def test_stale_revision_prevents_event_buffer_reconnect(monkeypatch, tmp_path: Path) -> None:
    worker = EventBufferWorker(
        41,
        "rtsp://camera/main",
        tmp_path,
        3_000_000,
        connection_revision=4,
    )
    checks: list[tuple[int, int | None]] = []
    states = iter(("current", "stale"))
    spawn_calls = 0

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return next(states)

    async def spawn(*_args, **_kwargs):
        nonlocal spawn_calls
        spawn_calls += 1
        return _FakeProcess(worker)

    async def immediate_timeout(awaitable, *, timeout):
        del timeout
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        raise TimeoutError

    monkeypatch.setattr(event_recording_module, "connection_revision_state", revision_state, raising=False)
    monkeypatch.setattr(event_recording_module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(event_recording_module.asyncio, "wait_for", immediate_timeout)

    await worker._run()

    assert checks == [(41, 4), (41, 4)]
    assert spawn_calls == 1


@pytest.mark.asyncio
async def test_none_revision_keeps_legacy_event_buffer_behavior(monkeypatch, tmp_path: Path) -> None:
    worker = EventBufferWorker(
        41,
        "rtsp://camera/main",
        tmp_path,
        3_000_000,
        connection_revision=None,
    )
    checks: list[tuple[int, int | None]] = []
    spawn_calls = 0

    async def revision_state(camera_id: int, expected_revision: int | None) -> str:
        checks.append((camera_id, expected_revision))
        return "current"

    async def spawn(*_args, **_kwargs):
        nonlocal spawn_calls
        spawn_calls += 1
        return _FakeProcess(worker, stop_worker=True)

    monkeypatch.setattr(event_recording_module, "connection_revision_state", revision_state, raising=False)
    monkeypatch.setattr(event_recording_module.asyncio, "create_subprocess_exec", spawn)

    await worker._run()

    assert checks == [(41, None)]
    assert spawn_calls == 1


class _SessionContext:
    def __init__(self, camera) -> None:
        self.camera = camera

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def scalars(self, _statement):
        return [self.camera]


class _ManagedFakeWorker:
    created: list["_ManagedFakeWorker"] = []

    def __init__(
        self,
        camera_id: int,
        stream_uri: str,
        output_dir: Path,
        rtsp_timeout_us: int,
        connection_revision: int | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.stream_uri = stream_uri
        self.output_dir = output_dir
        self.rtsp_timeout_us = rtsp_timeout_us
        self.connection_revision = connection_revision
        self.running = True
        self.stop_calls = 0
        self.start_calls = 0
        self.__class__.created.append(self)

    async def stop(self) -> None:
        self.stop_calls += 1
        self.running = False

    async def start(self) -> None:
        self.start_calls += 1
        self.running = True


@pytest.mark.asyncio
async def test_reconcile_replaces_same_uri_worker_when_revision_changes_and_preserves_event_owner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _ManagedFakeWorker.created.clear()
    manager = EventRecordingManager()
    manager.buffer_root = tmp_path / "event-buffer"
    old_worker = _ManagedFakeWorker(
        41,
        "rtsp://camera/main",
        tmp_path / "old-buffer",
        3_000_000,
        connection_revision=4,
    )
    manager._workers[41] = old_worker

    recorder_running = False
    monkeypatch.setattr(
        event_recording_module.recorder_manager,
        "is_running",
        lambda _camera_id: recorder_running,
    )
    manager.begin_event(41, datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc))
    assert manager.event_capture_required(41) is True
    recorder_running = True

    camera = SimpleNamespace(
        id=41,
        enabled=True,
        connection=SimpleNamespace(revision=5),
    )
    monkeypatch.setattr(event_recording_module, "SessionLocal", lambda: _SessionContext(camera))

    async def runtime_settings(_db):
        return SimpleNamespace(rtsp_timeout_us=3_000_000)

    monkeypatch.setattr(event_recording_module, "load_runtime_settings", runtime_settings)
    monkeypatch.setattr(
        event_recording_module,
        "resolve_stream",
        lambda _camera, _role: SimpleNamespace(uri="rtsp://camera/main"),
    )
    monkeypatch.setattr(event_recording_module, "EventBufferWorker", _ManagedFakeWorker)

    count = await manager.reconcile_once()

    assert count == 1
    assert old_worker.stop_calls == 1
    new_worker = manager._workers[41]
    assert new_worker is not old_worker
    assert new_worker.stream_uri == "rtsp://camera/main"
    assert new_worker.connection_revision == 5
    assert new_worker.start_calls == 1
    assert manager.event_capture_required(41) is True
