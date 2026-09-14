from datetime import datetime, timedelta, timezone

from app.services.motion_detection import (
    MotionConfidenceTracker,
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


def test_sensitivity_profiles_order_false_positive_tolerance() -> None:
    low = sensitivity_profile("low")
    medium = sensitivity_profile("medium")
    high = sensitivity_profile("high")

    assert (low.var_threshold, medium.var_threshold, high.var_threshold) == (32, 24, 16)
    assert low.min_area_ratio > medium.min_area_ratio > high.min_area_ratio
    assert low.min_zone_overlap_ratio > medium.min_zone_overlap_ratio > high.min_zone_overlap_ratio
    assert low.enter_confidence > medium.enter_confidence > high.enter_confidence
    assert low.confidence_gain < medium.confidence_gain < high.confidence_gain
    assert low.confidence_decay > medium.confidence_decay > high.confidence_decay
    assert low.global_change_ratio < medium.global_change_ratio < high.global_change_ratio


def test_confidence_tracker_accumulates_valid_motion_and_uses_hysteresis() -> None:
    tracker = MotionConfidenceTracker(sensitivity_profile("medium"))

    first = tracker.update(0.25)
    assert first.motion is False
    assert 0.0 < first.confidence < 0.65

    result = first
    for _ in range(8):
        result = tracker.update(0.25)
        if result.motion:
            break
    assert result.motion is True
    assert result.transitioned is True

    still_active = tracker.update(0.0)
    assert still_active.motion is True
    assert still_active.confidence > 0.20

    result = still_active
    for _ in range(10):
        result = tracker.update(0.0)
        if not result.motion:
            break
    assert result.motion is False
    assert result.transitioned is True


def test_confidence_tracker_suppression_resets_state() -> None:
    tracker = MotionConfidenceTracker(sensitivity_profile("high"))
    for _ in range(6):
        tracker.update(1.0)

    reset = tracker.update(1.0, suppressed=True)

    assert reset.motion is False
    assert reset.confidence == 0.0
    assert reset.transitioned is True


def test_confidence_tracker_reset_does_not_report_transition_before_motion_entry() -> None:
    tracker = MotionConfidenceTracker(sensitivity_profile("medium"))
    weak = tracker.update(0.1)
    assert weak.motion is False
    assert weak.confidence > 0.0

    reset = tracker.update(0.0, suppressed=True)

    assert reset.motion is False
    assert reset.confidence == 0.0
    assert reset.transitioned is False


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


def test_state_machine_coalesces_repeated_activity_inside_event_min_interval() -> None:
    state = MotionEventStateMachine(
        min_duration_ms=500,
        merge_gap_ms=10_000,
        event_min_interval_ms=60_000,
    )
    start = datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc)

    assert state.update(start, motion=True, score=0.2, zone_id=3) == []
    assert state.update(start + timedelta(seconds=1), motion=True, score=0.4, zone_id=3) == []
    assert state.update(start + timedelta(seconds=5), motion=False, score=0.0, zone_id=None) == []

    # The normal merge gap has expired, but this movement is still inside the
    # 60-second anchor interval, so it must extend the same event.
    assert state.update(start + timedelta(seconds=20), motion=True, score=0.8, zone_id=3) == []
    assert state.active is True
    assert state.update(start + timedelta(seconds=25), motion=False, score=0.0, zone_id=None) == []

    closed = state.update(start + timedelta(seconds=61), motion=False, score=0.0, zone_id=None)
    assert len(closed) == 1
    event = closed[0]
    assert event.started_at == start
    assert event.ended_at == start + timedelta(seconds=25)
    assert event.zone_id == 3
    assert event.peak_score == 0.8
    assert state.active is False


def test_state_machine_flush_discards_unconfirmed_candidate() -> None:
    state = MotionEventStateMachine(min_duration_ms=800, merge_gap_ms=3000)
    start = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)

    state.update(start, motion=True, score=0.3, zone_id=4)

    assert state.flush(start + timedelta(seconds=10)) == []
    assert state.active is False


def test_state_machine_flush_closes_confirmed_event_at_last_motion_time() -> None:
    state = MotionEventStateMachine(min_duration_ms=500, merge_gap_ms=3000)
    start = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)

    state.update(start, motion=True, score=0.3, zone_id=4)
    state.update(start + timedelta(seconds=1), motion=True, score=0.6, zone_id=4)
    state.update(start + timedelta(seconds=5), motion=True, score=0.8, zone_id=4)

    closed = state.flush(start + timedelta(seconds=30))

    assert len(closed) == 1
    assert closed[0].started_at == start
    assert closed[0].ended_at == start + timedelta(seconds=5)
    assert closed[0].peak_score == 0.8
    assert closed[0].zone_id == 4


def test_state_machine_flush_does_not_extend_to_pending_silence() -> None:
    state = MotionEventStateMachine(min_duration_ms=500, merge_gap_ms=10_000)
    start = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)

    state.update(start, motion=True, score=0.3, zone_id=9)
    state.update(start + timedelta(seconds=1), motion=True, score=0.6, zone_id=9)
    state.update(start + timedelta(seconds=5), motion=True, score=0.7, zone_id=9)
    state.update(start + timedelta(seconds=6), motion=False, score=0.0, zone_id=None)

    closed = state.flush(start + timedelta(seconds=30))

    assert len(closed) == 1
    assert closed[0].ended_at == start + timedelta(seconds=5)


def test_state_machine_flush_is_idempotent() -> None:
    state = MotionEventStateMachine(min_duration_ms=500, merge_gap_ms=3000)
    start = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)

    state.update(start, motion=True, score=0.3, zone_id=None)
    state.update(start + timedelta(seconds=1), motion=True, score=0.5, zone_id=None)

    assert len(state.flush(start + timedelta(seconds=2))) == 1
    assert state.flush(start + timedelta(seconds=3)) == []
