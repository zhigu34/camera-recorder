import numpy as np

from app.services.motion_analysis import MotionFrameAnalyzer


HEIGHT = 360
WIDTH = 640


def _frame(value: int = 0) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8)


def _warm(analyzer: MotionFrameAnalyzer, frame: np.ndarray) -> None:
    for _ in range(analyzer.warmup_frames):
        result = analyzer.analyze(frame, [])
        assert result.warming_up is True
        assert result.raw_score == 0.0
        assert result.primary_zone_id is None


def test_warmup_suppresses_motion_then_local_motion_is_detected() -> None:
    analyzer = MotionFrameAnalyzer("medium", analysis_fps=5)
    background = _frame()
    _warm(analyzer, background)

    changed = background.copy()
    changed[120:260, 220:420] = 255
    result = analyzer.analyze(changed, [])

    assert result.warming_up is False
    assert result.stabilizing is False
    assert result.global_change is False
    assert result.raw_score > 0.0
    assert result.moving_area_ratio > 0.0
    assert result.primary_zone_id is None


def test_whole_frame_brightness_change_enters_stabilization_and_converges() -> None:
    analyzer = MotionFrameAnalyzer("medium", analysis_fps=2)
    black = _frame(0)
    white = _frame(255)
    _warm(analyzer, black)

    transition = analyzer.analyze(white, [])
    assert transition.global_change is True
    assert transition.stabilizing is True
    assert transition.raw_score == 0.0
    assert transition.global_change_ratio >= 0.99

    suppressed = []
    for _ in range(analyzer.stabilization_frames):
        suppressed.append(analyzer.analyze(white, []))
    assert all(result.raw_score == 0.0 for result in suppressed)

    resumed = analyzer.analyze(white, [])
    assert resumed.global_change is False
    assert resumed.stabilizing is False


def test_repeated_global_transition_restarts_stabilization_window() -> None:
    analyzer = MotionFrameAnalyzer("medium", analysis_fps=2)
    black = _frame(0)
    white = _frame(255)
    gray = _frame(80)
    _warm(analyzer, black)

    first = analyzer.analyze(white, [])
    assert first.global_change is True

    analyzer.analyze(white, [])
    second = analyzer.analyze(gray, [])
    assert second.global_change is True
    assert second.stabilizing is True

    for _ in range(analyzer.stabilization_frames - 1):
        assert analyzer.analyze(gray, []).stabilizing is True
    assert analyzer.analyze(gray, []).stabilizing is True
    assert analyzer.analyze(gray, []).stabilizing is False


def test_large_local_object_is_not_misclassified_as_global_change() -> None:
    analyzer = MotionFrameAnalyzer("medium", analysis_fps=5)
    background = _frame()
    _warm(analyzer, background)

    changed = background.copy()
    changed[90:330, 320:640] = 255
    result = analyzer.analyze(changed, [])

    assert result.global_change is False
    assert result.raw_score > 0.0


def test_zone_overlap_accepts_motion_even_when_bbox_center_is_outside_zone() -> None:
    analyzer = MotionFrameAnalyzer("medium", analysis_fps=5)
    background = _frame()
    zone = {
        "id": 7,
        "enabled": True,
        "polygon": [[0.0, 0.0], [0.45, 0.0], [0.45, 1.0], [0.0, 1.0]],
    }
    for _ in range(analyzer.warmup_frames):
        analyzer.analyze(background, [zone])

    changed = background.copy()
    changed[120:260, 250:400] = 255
    result = analyzer.analyze(changed, [zone])

    # Bounding-box center is around x=0.508, outside the zone ending at x=0.45,
    # but more than 25% of the moving contour is actually inside the zone.
    assert result.raw_score > 0.0
    assert result.primary_zone_id == 7
    assert result.matched_zone_ids == [7]


def test_zone_overlap_rejects_small_edge_touch() -> None:
    analyzer = MotionFrameAnalyzer("medium", analysis_fps=5)
    background = _frame()
    zone = {
        "id": 7,
        "enabled": True,
        "polygon": [[0.0, 0.0], [0.45, 0.0], [0.45, 1.0], [0.0, 1.0]],
    }
    for _ in range(analyzer.warmup_frames):
        analyzer.analyze(background, [zone])

    changed = background.copy()
    changed[120:260, 280:420] = 255
    result = analyzer.analyze(changed, [zone])

    assert result.raw_score == 0.0
    assert result.primary_zone_id is None
    assert result.matched_zone_ids == []


def test_small_zone_uses_zone_area_threshold_not_whole_frame_threshold() -> None:
    analyzer = MotionFrameAnalyzer("medium", analysis_fps=5)
    background = _frame()
    zone = {
        "id": 11,
        "enabled": True,
        "polygon": [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]],
    }
    for _ in range(analyzer.warmup_frames):
        analyzer.analyze(background, [zone])

    changed = background.copy()
    changed[45:60, 75:90] = 255
    result = analyzer.analyze(changed, [zone])

    assert result.raw_score > 0.0
    assert result.primary_zone_id == 11


def test_disabled_zones_are_ignored_and_no_enabled_zones_mean_full_frame() -> None:
    analyzer = MotionFrameAnalyzer("medium", analysis_fps=5)
    background = _frame()
    disabled_zone = {
        "id": 2,
        "enabled": False,
        "polygon": [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]],
    }
    for _ in range(analyzer.warmup_frames):
        analyzer.analyze(background, [disabled_zone])

    changed = background.copy()
    changed[100:220, 100:260] = 255
    result = analyzer.analyze(changed, [disabled_zone])

    assert result.raw_score > 0.0
    assert result.primary_zone_id is None
    assert result.matched_zone_ids == []


def test_multiple_matching_zones_select_largest_intersection_as_primary() -> None:
    analyzer = MotionFrameAnalyzer("high", analysis_fps=5)
    background = _frame()
    zones = [
        {
            "id": 1,
            "enabled": True,
            "polygon": [[0.2, 0.2], [0.65, 0.2], [0.65, 0.8], [0.2, 0.8]],
        },
        {
            "id": 3,
            "enabled": True,
            "polygon": [[0.45, 0.2], [0.9, 0.2], [0.9, 0.8], [0.45, 0.8]],
        },
    ]
    for _ in range(analyzer.warmup_frames):
        analyzer.analyze(background, zones)

    changed = background.copy()
    changed[120:260, 260:500] = 255
    result = analyzer.analyze(changed, zones)

    assert set(result.matched_zone_ids) == {1, 3}
    assert result.primary_zone_id == 3
    assert result.raw_score > 0.0
