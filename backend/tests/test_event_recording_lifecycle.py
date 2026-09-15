import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.event_recording import EventRecordingManager
from app.services.motion_detection import MotionEventStateMachine


def test_confirmed_motion_exposes_original_event_start_for_preroll_pin() -> None:
    state = MotionEventStateMachine(
        min_duration_ms=100,
        merge_gap_ms=1000,
        event_min_interval_ms=0,
    )
    started_at = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

    state.update(started_at, motion=True, score=0.7, zone_id=None)
    state.update(started_at + timedelta(milliseconds=150), motion=True, score=0.8, zone_id=None)

    assert state.active is True
    assert state.started_at == started_at


def test_active_event_pin_prevents_ring_cleanup_from_dropping_event_start(tmp_path: Path) -> None:
    manager = EventRecordingManager()
    camera_id = 9
    old = time.time() - 3600
    expected: list[str] = []

    for second in range(41):
        path = tmp_path / f"2026-09-15_12-00-{second:02d}.mkv"
        path.write_bytes(b"segment")
        os.utime(path, (old, old))
        if second >= 5:
            expected.append(path.name)

    manager.begin_event(
        camera_id,
        datetime(2026, 9, 15, 12, 0, 10, tzinfo=timezone.utc),
    )
    manager._cleanup_ring(camera_id, tmp_path)

    assert sorted(path.name for path in tmp_path.glob("*.mkv")) == expected

    manager.end_event(camera_id)
    manager._cleanup_ring(camera_id, tmp_path)
    assert len(list(tmp_path.glob("*.mkv"))) == 1
