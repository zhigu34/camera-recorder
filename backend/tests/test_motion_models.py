from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.motion import (
    MotionDetectionUpdate,
    MotionEventRead,
    MotionZoneCreate,
)


def test_motion_detection_defaults_and_bounds() -> None:
    payload = MotionDetectionUpdate(enabled=True)
    assert payload.enabled is True
    assert payload.sensitivity == "medium"
    assert payload.analysis_fps == 5
    assert payload.analysis_width == 640
    assert payload.min_duration_ms == 800
    assert payload.merge_gap_ms == 10_000
    assert payload.event_min_interval_ms == 60_000

    with pytest.raises(ValidationError):
        MotionDetectionUpdate(enabled=True, analysis_fps=0)
    with pytest.raises(ValidationError):
        MotionDetectionUpdate(enabled=True, analysis_fps=11)
    with pytest.raises(ValidationError):
        MotionDetectionUpdate(enabled=True, analysis_width=319)
    with pytest.raises(ValidationError):
        MotionDetectionUpdate(enabled=True, min_duration_ms=99)
    with pytest.raises(ValidationError):
        MotionDetectionUpdate(enabled=True, merge_gap_ms=30_001)
    with pytest.raises(ValidationError):
        MotionDetectionUpdate(enabled=True, event_min_interval_ms=-1)
    with pytest.raises(ValidationError):
        MotionDetectionUpdate(enabled=True, event_min_interval_ms=600_001)


def test_zone_polygon_requires_three_normalized_points() -> None:
    with pytest.raises(ValidationError):
        MotionZoneCreate(name="入口", polygon=[[0.1, 0.1], [0.9, 0.9]])

    with pytest.raises(ValidationError):
        MotionZoneCreate(
            name="入口",
            polygon=[[0.1, 0.1], [1.2, 0.2], [0.5, 0.9]],
        )

    zone = MotionZoneCreate(
        name="入口",
        polygon=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
    )
    assert zone.enabled is True
    assert zone.polygon[0] == [0.1, 0.1]


def test_motion_event_read_preserves_utc_time_fields() -> None:
    started = datetime(2026, 9, 13, 4, 30, tzinfo=timezone.utc)
    ended = datetime(2026, 9, 13, 4, 31, tzinfo=timezone.utc)
    event = MotionEventRead(
        id=1,
        camera_id=2,
        zone_id=None,
        recording_id=None,
        started_at=started,
        ended_at=ended,
        peak_score=0.42,
        snapshot_path=None,
        metadata_json=None,
        created_at=ended,
    )
    assert event.started_at == started
    assert event.ended_at == ended
