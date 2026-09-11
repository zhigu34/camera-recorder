from app.api.playback_metrics import BrowserPlaybackMetric
from app.services.playback_client_metrics import PlaybackClientMetrics


def _sample(**overrides):
    payload = {
        "attempt_id": "attempt-1",
        "recording_id": 1,
        "event": "first_frame",
        "duration_ms": 420.0,
        "metadata_ms": 80.0,
        "loaded_data_ms": 160.0,
        "canplay_ms": 220.0,
        "playing_ms": 350.0,
        "browser": "Chrome",
        "browser_version": "153",
        "platform": "macOS",
        "codec": "hevc",
        "playback_mode": "original",
        "source_kind": "openlist_stream",
        "signal": "video_frame_callback",
        "hevc_hint": "probably",
        "media_error_code": None,
        "ready_state": 4,
        "network_state": 1,
    }
    payload.update(overrides)
    return payload


def test_client_metrics_group_compatibility_and_first_frame_latency():
    metrics = PlaybackClientMetrics()
    metrics.record(_sample(attempt_id="success-1", duration_ms=300.0))
    metrics.record(_sample(attempt_id="success-2", duration_ms=500.0))
    metrics.record(
        _sample(
            attempt_id="failure-1",
            event="startup_error",
            duration_ms=240.0,
            signal="media_error",
            media_error_code=3,
        )
    )

    snapshot = metrics.snapshot()

    assert snapshot["events"]["first_frame"]["count"] == 2
    assert snapshot["events"]["first_frame"]["avg_ms"] == 400.0
    assert snapshot["events"]["startup_error"]["count"] == 1

    compatibility = snapshot["compatibility"][0]
    assert compatibility["attempts"] == 3
    assert compatibility["successful_starts"] == 2
    assert compatibility["startup_errors"] == 1
    assert compatibility["success_rate"] == 66.67
    assert compatibility["first_frame"]["avg_ms"] == 400.0
    assert compatibility["frame_signals"] == {"video_frame_callback": 2}
    assert compatibility["hevc_hints"] == {"probably": 3}


def test_decode_ready_is_measured_but_not_counted_as_final_attempt():
    metrics = PlaybackClientMetrics()
    metrics.record(_sample(event="decode_ready", duration_ms=150.0, signal="loadeddata"))

    snapshot = metrics.snapshot()

    assert snapshot["events"]["decode_ready"]["count"] == 1
    assert snapshot["events"]["decode_ready"]["avg_ms"] == 150.0
    assert snapshot["compatibility"] == []


def test_browser_metric_schema_rejects_sensitive_oversized_labels():
    metric = BrowserPlaybackMetric(**_sample())
    assert metric.browser == "Chrome"
    assert metric.event == "first_frame"
