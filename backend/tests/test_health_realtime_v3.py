import inspect

from fastapi.testclient import TestClient

from app.api import health as health_api
from app.main import app


def test_realtime_health_endpoint_is_current_state_only() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/realtime")

    assert response.status_code == 200
    body = response.json()
    assert body["uptime_seconds"] >= 0
    assert isinstance(body["camera_health"], list)
    assert "cameras" in body
    assert "storage" in body
    assert "upload" in body
    assert "connectivity_monitor" in body
    assert "recordings_24h" not in body
    assert "recording_completeness" not in body
    assert "used_bytes" in body["storage"]
    assert "local_recordings_bytes" in body["storage"]
    assert body["storage"]["used_bytes"] == (
        body["storage"]["total_bytes"] - body["storage"]["free_bytes"]
    )


def test_health_websocket_uses_realtime_contract() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/status") as websocket:
            message = websocket.receive_json()

    assert message["type"] == "health.realtime"
    assert "camera_health" in message["data"]
    assert "recordings_24h" not in message["data"]


def test_websocket_calls_realtime_builder_directly() -> None:
    source = inspect.getsource(health_api.status_websocket)

    assert "realtime_health_snapshot" in source
    assert "_schedule_aware_snapshot" not in source


def test_legacy_summary_remains_available_during_migration() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/summary")

    assert response.status_code == 200
    assert "recordings_24h" in response.json()
