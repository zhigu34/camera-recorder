import numpy as np

from app.services.motion_worker import (
    MotionFrameAnalyzer,
    build_motion_command,
    scaled_dimensions,
    select_motion_path,
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


def _warm(analyzer: MotionFrameAnalyzer, frame: np.ndarray, count: int = 12) -> None:
    for _ in range(count):
        analyzer.analyze(frame, [])


def test_frame_analyzer_detects_large_change_after_background_warmup() -> None:
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    analyzer = MotionFrameAnalyzer("medium")
    _warm(analyzer, frame)

    changed = frame.copy()
    changed[120:300, 220:500] = 255
    result = analyzer.analyze(changed, [])

    assert result.motion is True
    assert result.score > 0.01
    assert result.zone_ids == [None]


def test_frame_analyzer_ignores_motion_outside_enabled_zone() -> None:
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    analyzer = MotionFrameAnalyzer("medium")
    _warm(analyzer, frame)

    changed = frame.copy()
    changed[220:340, 420:620] = 255
    zones = [
        {
            "id": 9,
            "enabled": True,
            "polygon": [[0.0, 0.0], [0.35, 0.0], [0.35, 0.4], [0.0, 0.4]],
        }
    ]
    result = analyzer.analyze(changed, zones)

    assert result.motion is False
    assert result.zone_ids == []
