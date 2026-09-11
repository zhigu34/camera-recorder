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


def test_health_websocket_sends_snapshot() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/status") as websocket:
            message = websocket.receive_json()

    assert message["type"] == "health.snapshot"
    assert "uptime_seconds" in message["data"]
    assert "camera_health" in message["data"]
