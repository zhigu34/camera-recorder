from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import event_recording as event_recording_module
from app.services import event_recording_link as link_module
from app.services import recording_start as recording_start_module
from app.services.event_recording import EventRecordingManager, should_buffer_event_camera


class _FakeWorker:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.stream_uri = "rtsp://camera/main"
        self.running = True
        self.stop_calls = 0
        self.start_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1
        self.running = False

    async def start(self) -> None:
        self.start_calls += 1
        self.running = True


class _ScalarSession:
    def __init__(self, value) -> None:
        self.value = value

    async def scalar(self, _statement):
        return self.value


class _SessionContext:
    def __init__(self, value) -> None:
        self.session = _ScalarSession(value)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_active_event_capture_keeps_ring_eligible_when_regular_recorder_starts() -> None:
    assert should_buffer_event_camera(
        camera_enabled=True,
        detection_enabled=True,
        recorder_running=True,
        event_capture_active=True,
    ) is True


@pytest.mark.asyncio
async def test_capture_owned_at_event_start_survives_mid_event_regular_start(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = EventRecordingManager()
    camera_id = 21
    worker = _FakeWorker(tmp_path)
    manager._workers[camera_id] = worker
    recorder_running = False
    monkeypatch.setattr(
        event_recording_module.recorder_manager,
        "is_running",
        lambda _camera_id: recorder_running,
    )

    started_at = datetime(2026, 9, 16, 12, 0, 10, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(seconds=4)
    for second in range(5, 15):
        (tmp_path / f"2026-09-16_12-00-{second:02d}.mkv").write_bytes(b"segment")

    manager.begin_event(camera_id, started_at)
    assert manager.event_capture_required(camera_id) is True

    recorder_running = True
    materialized: list[tuple[list[str], datetime, float]] = []

    async def fake_materialize_clip(*, camera_id: int, segments, started_at, requested_duration):
        assert camera_id == 21
        materialized.append(([path.name for path in segments], started_at, requested_duration))
        return 91

    monkeypatch.setattr(manager, "_materialize_clip", fake_materialize_clip)

    recording_id = await manager.capture(camera_id, started_at, ended_at)

    assert recording_id == 91
    assert materialized
    assert materialized[0][0][0] == "2026-09-16_12-00-05.mkv"
    assert materialized[0][0][-1] == "2026-09-16_12-00-14.mkv"
    assert worker.stop_calls == 1
    assert worker.start_calls == 0


@pytest.mark.asyncio
async def test_owned_event_clip_wins_over_regular_recording_started_mid_event(monkeypatch) -> None:
    regular_recording = SimpleNamespace(id=44)
    monkeypatch.setattr(link_module, "SessionLocal", lambda: _SessionContext(regular_recording))
    monkeypatch.setattr(
        link_module.event_recording_manager,
        "event_capture_required",
        lambda camera_id: camera_id == 21,
        raising=False,
    )
    capture_calls: list[tuple[int, datetime, datetime]] = []

    async def capture(camera_id: int, started_at: datetime, ended_at: datetime) -> int:
        capture_calls.append((camera_id, started_at, ended_at))
        return 91

    monkeypatch.setattr(link_module.event_recording_manager, "capture", capture)
    monkeypatch.setattr(link_module.recorder_manager, "is_running", lambda _camera_id: True)

    started_at = datetime(2026, 9, 16, 12, 0, 10, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(seconds=4)
    recording_id = await link_module.resolve_event_recording(21, started_at, ended_at)

    assert recording_id == 91
    assert capture_calls == [(21, started_at, ended_at)]


@pytest.mark.asyncio
async def test_regular_recorder_does_not_stop_buffer_that_owns_active_event(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        recording_start_module.event_recording_manager,
        "event_capture_required",
        lambda camera_id: camera_id == 21,
        raising=False,
    )

    async def stop_event_buffer(camera_id: int) -> None:
        calls.append(f"stop-buffer-{camera_id}")

    async def start_recorder(camera) -> dict:
        calls.append(f"start-recorder-{camera.id}")
        return {"camera_id": camera.id, "state": "RECORDING", "pid": 1}

    monkeypatch.setattr(recording_start_module.event_recording_manager, "stop_camera", stop_event_buffer)
    monkeypatch.setattr(recording_start_module.recorder_manager, "start", start_recorder)

    result = await recording_start_module.start_regular_recorder(SimpleNamespace(id=21))

    assert result["state"] == "RECORDING"
    assert calls == ["start-recorder-21"]
