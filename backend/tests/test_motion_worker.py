from app.services.motion_analysis import MotionAnalysisResult
from app.services.motion_detection import MotionConfidenceResult
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
