from fastapi.testclient import TestClient

from app.main import app


def test_health_summary_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["uptime_seconds"] >= 0
    assert "total" in body["cameras"]
    assert "recording" in body["cameras"]
    assert "abnormal" in body["cameras"]
    assert "segments" in body["recordings_24h"]
    assert "used_percent" in body["storage"]
    assert isinstance(body["camera_health"], list)


def test_health_trends_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/trends?hours=24&bucket_minutes=60")

    assert response.status_code == 200
    body = response.json()
    assert body["hours"] == 24
    assert body["bucket_minutes"] == 60
    assert body["sample_interval_seconds"] == 60
    assert body["retention_days"] == 7
    assert "online_rate" in body["overall"]
    assert "recording_completeness" in body["overall"]
    assert isinstance(body["cameras"], list)
    assert isinstance(body["timeline"], list)


def test_health_trends_reject_invalid_window() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/trends?hours=0")

    assert response.status_code == 422


def test_stability_report_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/stability?hours=24")

    assert response.status_code == 200
    body = response.json()
    assert body["hours"] == 24
    assert body["overall"]["verdict"] in {"pass", "fail", "collecting"}
    assert body["criteria"]["min_sample_coverage"] == 95.0
    assert body["criteria"]["min_online_rate"] == 99.5
    assert body["criteria"]["max_longest_outage_seconds"] == 120
    assert "ffmpeg_failures" in body["overall"]
    assert "failure_streaks" in body["overall"]
    assert "longest_offline_seconds" in body["overall"]
    assert isinstance(body["cameras"], list)


def test_stability_report_reject_invalid_window() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/stability?hours=169")

    assert response.status_code == 422


def test_health_websocket_sends_snapshot() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/status") as websocket:
            message = websocket.receive_json()

    assert message["type"] == "health.snapshot"
    assert "uptime_seconds" in message["data"]
    assert "camera_health" in message["data"]
