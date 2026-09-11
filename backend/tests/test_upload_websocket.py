from fastapi.testclient import TestClient

from app.main import app


def test_upload_websocket_snapshot() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/uploads") as websocket:
            payload = websocket.receive_json()

    assert payload["type"] == "uploads.snapshot"
    assert isinstance(payload["tasks"], list)
    assert isinstance(payload["status"], dict)
    assert isinstance(payload["status"].get("counts"), dict)
