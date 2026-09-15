import inspect

from fastapi.testclient import TestClient

from app.main import app


def test_health_reliability_endpoint_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/reliability?hours=24")

    assert response.status_code == 200
    body = response.json()
    assert body["hours"] == 24
    assert set(("generated_at", "criteria", "overall", "issues", "cameras")) <= set(body)
    assert "recorder_availability_rate" in body["overall"]
    assert "recording_completeness" in body["overall"]
    assert "recording_gap_count" in body["overall"]
    assert "missing_recording_seconds" in body["overall"]
    assert isinstance(body["issues"], list)
    assert isinstance(body["cameras"], list)


def test_health_reliability_accepts_only_supported_windows() -> None:
    with TestClient(app) as client:
        assert client.get("/api/health/reliability?hours=72").status_code == 200
        assert client.get("/api/health/reliability?hours=12").status_code == 422


def test_reliability_builder_is_not_nested_on_legacy_reports() -> None:
    from app.services import health_reliability as module

    source = inspect.getsource(module.health_reliability)
    assert "health_trends(" not in source
    assert "stability_report(" not in source


def test_compatibility_stability_reuses_unified_reliability_builder() -> None:
    from app.services import stability_report as module

    source = inspect.getsource(module.stability_report)
    assert "health_trends(" not in source
    assert "build_health_reliability_report(" in source


def test_reliability_camera_contract_exposes_diagnostics_when_present() -> None:
    from app.services.health_reliability import camera_reliability_row

    row = camera_reliability_row(
        camera_id=7,
        name="Gate",
        ip="192.0.2.7",
        monitored=True,
        sample_count=1440,
        expected_minutes=1440,
        online_samples=1439,
        recording_segments=143,
        complete_segments=142,
        diagnostics=[
            {
                "start_at": "2026-09-15T10:00:00+00:00",
                "end_at": "2026-09-15T10:05:00+00:00",
                "duration_seconds": 300,
                "cause": "unknown",
                "cause_label": "未知原因",
                "detail": "没有匹配证据",
                "confidence": "low",
            }
        ],
        outage_durations=[],
        ffmpeg_failures=0,
        failure_streaks=0,
        max_consecutive_failures=0,
        current_offline_seconds=0,
        max_ffmpeg_failures=3,
    )

    assert row["recording_gap_count"] == 1
    assert row["missing_recording_seconds"] == 300
    assert row["unexplained_recording_gaps"] == 1
    assert row["diagnostics"][0]["cause"] == "unknown"
    assert row["primary_problem"]["cause"] == "unknown"
    assert "recorder_availability_rate" in row
