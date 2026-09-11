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


def test_health_websocket_sends_snapshot() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/status") as websocket:
            message = websocket.receive_json()

    assert message["type"] == "health.snapshot"
    assert "uptime_seconds" in message["data"]
    assert "camera_health" in message["data"]
