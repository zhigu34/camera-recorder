from datetime import datetime, timedelta, timezone

from app.services.motion_detection import (
    MotionEventStateMachine,
    point_in_polygon,
    sensitivity_profile,
    zones_for_point,
)


def test_sensitivity_profiles_are_ordered_by_minimum_area() -> None:
    low = sensitivity_profile("low")
    medium = sensitivity_profile("medium")
    high = sensitivity_profile("high")

    assert low.min_area_ratio > medium.min_area_ratio > high.min_area_ratio
    assert low.var_threshold > medium.var_threshold > high.var_threshold


def test_point_in_polygon_and_no_zone_full_frame_behavior() -> None:
    square = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
    assert point_in_polygon((0.5, 0.5), square) is True
    assert point_in_polygon((0.1, 0.1), square) is False

    assert zones_for_point((0.5, 0.5), []) == [None]


def test_zones_for_point_returns_only_enabled_matches() -> None:
    zones = [
        {"id": 1, "enabled": True, "polygon": [[0.1, 0.1], [0.6, 0.1], [0.6, 0.6], [0.1, 0.6]]},
        {"id": 2, "enabled": False, "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]},
        {"id": 3, "enabled": True, "polygon": [[0.4, 0.4], [0.9, 0.4], [0.9, 0.9], [0.4, 0.9]]},
    ]
    assert zones_for_point((0.5, 0.5), zones) == [1, 3]
    assert zones_for_point((0.95, 0.95), zones) == []


def test_state_machine_rejects_motion_shorter_than_min_duration() -> None:
    state = MotionEventStateMachine(min_duration_ms=800, merge_gap_ms=3000)
    start = datetime(2026, 9, 13, 4, 30, tzinfo=timezone.utc)

    assert state.update(start, motion=True, score=0.2, zone_id=None) == []
    assert state.update(start + timedelta(milliseconds=500), motion=False, score=0.0, zone_id=None) == []
    assert state.update(start + timedelta(seconds=4), motion=False, score=0.0, zone_id=None) == []


def test_state_machine_confirms_and_merges_motion_inside_gap() -> None:
    state = MotionEventStateMachine(min_duration_ms=800, merge_gap_ms=3000)
    start = datetime(2026, 9, 13, 4, 30, tzinfo=timezone.utc)

    assert state.update(start, motion=True, score=0.2, zone_id=7) == []
    assert state.update(start + timedelta(milliseconds=900), motion=True, score=0.7, zone_id=7) == []
    assert state.active is True

    assert state.update(start + timedelta(seconds=2), motion=False, score=0.0, zone_id=None) == []
    assert state.update(start + timedelta(seconds=4), motion=True, score=0.5, zone_id=7) == []
    assert state.active is True

    assert state.update(start + timedelta(seconds=5), motion=False, score=0.0, zone_id=None) == []
    closed = state.update(start + timedelta(seconds=9), motion=False, score=0.0, zone_id=None)

    assert len(closed) == 1
    event = closed[0]
    assert event.started_at == start
    assert event.ended_at == start + timedelta(seconds=5)
    assert event.zone_id == 7
    assert event.peak_score == 0.7
    assert state.active is False
