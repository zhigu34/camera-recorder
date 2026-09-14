import inspect
from datetime import datetime, timedelta, timezone

import numpy as np

import app.services.motion_manager as motion_manager_module
import app.services.motion_worker as motion_worker_module
from app.services.motion_analysis import MotionAnalysisResult, MotionFrameAnalyzer
from app.services.motion_detection import (
    MotionConfidenceResult,
    MotionConfidenceTracker,
    MotionEventStateMachine,
    sensitivity_profile,
)
from app.services.motion_worker import (
    build_motion_command,
    runtime_diagnostics,
    runtime_state_for_analysis,
    scaled_dimensions,
    select_motion_path,
    snapshot_quality_key,
)


def test_motion_stream_prefers_configured_then_inferred_substream() -> None:
    assert select_motion_path("/ch1/main", "/custom/sub") == ("/custom/sub", "sub")
    assert select_motion_path("/ch1/main", None) == ("/ch1/sub", "sub")
    assert select_motion_path("/Streaming/Channels/101", None) == (
        "/Streaming/Channels/101",
        "main",
    )


def test_scaled_dimensions_preserve_aspect_ratio_and_even_height() -> None:
    assert scaled_dimensions(1920, 1080, 640) == (640, 360)
    assert scaled_dimensions(640, 480, 960) == (640, 480)
    assert scaled_dimensions(1280, 853, 640) == (640, 426)


def test_motion_command_uses_tcp_low_rate_bgr_rawvideo() -> None:
    command = build_motion_command(
        ip="192.0.2.20",
        port=554,
        username="admin",
        password="p@ss word",
        rtsp_path="/ch1/sub",
        rtsp_timeout_us=5_000_000,
        fps=5,
        width=640,
    )
    assert command[0].endswith("ffmpeg")
    assert command[command.index("-rtsp_transport") + 1] == "tcp"
    assert command[command.index("-timeout") + 1] == "5000000"
    assert command[command.index("-vf") + 1] == "fps=5,scale='min(640,iw)':-2"
    assert command[command.index("-pix_fmt") + 1] == "bgr24"
    assert command[-2:] == ["rawvideo", "pipe:1"]
    assert "rtsp://admin:p%40ss%20word@192.0.2.20:554/ch1/sub" in command


def _analysis(
    *,
    raw_score: float = 0.0,
    primary_zone_id: int | None = None,
    global_change: bool = False,
    warming_up: bool = False,
    stabilizing: bool = False,
    moving_area_ratio: float = 0.0,
    global_change_ratio: float = 0.0,
) -> MotionAnalysisResult:
    return MotionAnalysisResult(
        raw_score=raw_score,
        primary_zone_id=primary_zone_id,
        matched_zone_ids=[] if primary_zone_id is None else [primary_zone_id],
        global_change=global_change,
        warming_up=warming_up,
        stabilizing=stabilizing,
        moving_area_ratio=moving_area_ratio,
        global_change_ratio=global_change_ratio,
    )


def _confidence(value: float, *, motion: bool = False) -> MotionConfidenceResult:
    return MotionConfidenceResult(motion=motion, confidence=value, transitioned=False)


def test_runtime_state_reflects_algorithm_phase() -> None:
    assert runtime_state_for_analysis(_analysis(warming_up=True)) == "warming_up"
    assert runtime_state_for_analysis(_analysis(global_change=True)) == "stabilizing"
    assert runtime_state_for_analysis(_analysis(stabilizing=True)) == "stabilizing"
    assert runtime_state_for_analysis(_analysis(raw_score=0.4)) == "running"


def test_runtime_diagnostics_exposes_only_v2_observability_fields() -> None:
    diagnostics = runtime_diagnostics(
        _analysis(
            raw_score=0.42,
            primary_zone_id=7,
            moving_area_ratio=0.08,
            global_change_ratio=0.12,
        ),
        _confidence(0.72, motion=True),
    )

    assert diagnostics == {
        "confidence": 0.72,
        "raw_score": 0.42,
        "moving_area_ratio": 0.08,
        "global_change_ratio": 0.12,
        "primary_zone_id": 7,
        "global_change": False,
    }


def test_snapshot_quality_rejects_suppressed_or_empty_frames() -> None:
    confidence = _confidence(0.8, motion=True)

    assert snapshot_quality_key(_analysis(warming_up=True, raw_score=0.9), confidence) is None
    assert snapshot_quality_key(_analysis(stabilizing=True, raw_score=0.9), confidence) is None
    assert snapshot_quality_key(_analysis(global_change=True, raw_score=0.9), confidence) is None
    assert snapshot_quality_key(_analysis(raw_score=0.0), confidence) is None


def test_snapshot_quality_prefers_confidence_then_raw_score() -> None:
    lower_confidence = snapshot_quality_key(
        _analysis(raw_score=0.95),
        _confidence(0.60, motion=True),
    )
    higher_confidence = snapshot_quality_key(
        _analysis(raw_score=0.30),
        _confidence(0.70, motion=True),
    )
    same_confidence_better_raw = snapshot_quality_key(
        _analysis(raw_score=0.80),
        _confidence(0.70, motion=True),
    )

    assert lower_confidence is not None
    assert higher_confidence is not None
    assert same_confidence_better_raw is not None
    assert higher_confidence > lower_confidence
    assert same_confidence_better_raw > higher_confidence


def test_event_continuity_across_global_suppression_keeps_one_anchor_and_snapshot() -> None:
    profile = sensitivity_profile("medium")
    tracker = MotionConfidenceTracker(profile)
    state = MotionEventStateMachine(
        min_duration_ms=100,
        merge_gap_ms=1500,
        event_min_interval_ms=0,
    )
    start = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)
    closed = []
    best_quality: tuple[float, float] | None = None
    best_marker: str | None = None
    last_stable_motion_at: datetime | None = None

    for index in range(5):
        timestamp = start + timedelta(milliseconds=index * 200)
        analysis = _analysis(raw_score=1.0)
        confidence = tracker.update(analysis.raw_score)
        closed.extend(
            state.update(
                timestamp,
                motion=confidence.motion,
                score=confidence.confidence,
                zone_id=None,
            )
        )
        quality = snapshot_quality_key(analysis, confidence)
        if quality is not None and (best_quality is None or quality >= best_quality):
            best_quality = quality
            best_marker = f"initial-{index}"
        if confidence.motion:
            last_stable_motion_at = timestamp

    assert state.active is True
    assert last_stable_motion_at is not None
    assert best_quality is not None
    snapshot_before_suppression = (best_quality, best_marker)

    for index in range(3):
        timestamp = start + timedelta(milliseconds=1000 + index * 200)
        analysis = _analysis(
            raw_score=0.0,
            global_change=index == 0,
            stabilizing=True,
            global_change_ratio=0.9,
        )
        confidence = tracker.update(analysis.raw_score, suppressed=True)
        closed.extend(
            state.update(
                timestamp,
                motion=confidence.motion,
                score=confidence.confidence,
                zone_id=None,
                end_boundary_at=last_stable_motion_at,
            )
        )
        assert snapshot_quality_key(analysis, confidence) is None

    assert (best_quality, best_marker) == snapshot_before_suppression
    assert closed == []

    for index in range(4):
        timestamp = start + timedelta(milliseconds=1600 + index * 200)
        analysis = _analysis(raw_score=1.0)
        confidence = tracker.update(analysis.raw_score)
        closed.extend(
            state.update(
                timestamp,
                motion=confidence.motion,
                score=confidence.confidence,
                zone_id=None,
            )
        )

    assert closed == []
    assert state.active is True

    state.update(start + timedelta(milliseconds=2600), motion=False, score=0.0, zone_id=None)
    closed = state.update(
        start + timedelta(milliseconds=4300),
        motion=False,
        score=0.0,
        zone_id=None,
    )
    assert len(closed) == 1
    assert closed[0].started_at == start + timedelta(milliseconds=600)
    assert closed[0].peak_score >= 0.72


def test_suppression_closure_uses_last_valid_stable_motion_boundary() -> None:
    state = MotionEventStateMachine(
        min_duration_ms=100,
        merge_gap_ms=500,
        event_min_interval_ms=0,
    )
    start = datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc)
    state.update(start, motion=True, score=0.6, zone_id=3)
    last_motion = start + timedelta(milliseconds=200)
    state.update(last_motion, motion=True, score=0.8, zone_id=3)
    assert state.active is True

    state.update(
        start + timedelta(milliseconds=400),
        motion=False,
        score=0.0,
        zone_id=None,
        end_boundary_at=last_motion,
    )
    closed = state.update(
        start + timedelta(milliseconds=1000),
        motion=False,
        score=0.0,
        zone_id=None,
        end_boundary_at=last_motion,
    )

    assert len(closed) == 1
    assert closed[0].ended_at == last_motion
    assert closed[0].peak_score == 0.8


def test_disconnect_flush_emits_once_and_replacement_analyzer_starts_fresh() -> None:
    state = MotionEventStateMachine(
        min_duration_ms=100,
        merge_gap_ms=3000,
        event_min_interval_ms=0,
    )
    start = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    state.update(start, motion=True, score=0.5, zone_id=None)
    last_motion = start + timedelta(milliseconds=200)
    state.update(last_motion, motion=True, score=0.7, zone_id=None)

    flushed = state.flush(start + timedelta(seconds=30))
    assert len(flushed) == 1
    assert flushed[0].ended_at == last_motion
    assert state.flush(start + timedelta(seconds=31)) == []

    replacement = MotionFrameAnalyzer("medium", analysis_fps=2)
    blank = np.zeros((360, 640, 3), dtype=np.uint8)
    first = replacement.analyze(blank, [])
    assert first.warming_up is True
    assert first.raw_score == 0.0


def test_motion_failure_path_has_no_recorder_lifecycle_coupling() -> None:
    source = inspect.getsource(motion_worker_module) + inspect.getsource(motion_manager_module)

    assert "recorder_manager" not in source
    assert "restart_recording" not in source
    assert "stop_recording" not in source
