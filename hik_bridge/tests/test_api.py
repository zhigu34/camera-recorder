from fastapi.testclient import TestClient

from hik_bridge.app import create_app
from hik_bridge.service import HikBridgeService


class FakeSdk:
    def __init__(self, available=True):
        self.runtime_available = available
        self.callback = None

    def initialize(self):
        pass

    def cleanup(self):
        pass

    def login(self, host, port, username, password):
        return 3, {"serial_number": "SER9", "device_type": 7}

    def logout(self, user_id):
        pass

    def start_realplay(self, user_id, channel, stream_type, callback):
        self.callback = callback
        return 4

    def stop_realplay(self, handle):
        pass


def test_health_reports_missing_runtime_without_failing_service():
    app = create_app(HikBridgeService(FakeSdk(False)))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "runtime_available": False}


def test_probe_and_stream_urls_never_echo_credentials():
    sdk = FakeSdk(True)
    app = create_app(HikBridgeService(sdk))
    with TestClient(app) as client:
        probe = client.post(
            "/probe",
            json={
                "host": "10.0.0.8",
                "port": 8000,
                "username": "admin",
                "password": "secret",
            },
        )
        assert probe.status_code == 200
        assert probe.json()["serial_number"] == "SER9"
        created = client.post(
            "/streams",
            json={
                "host": "10.0.0.8",
                "port": 8000,
                "username": "admin",
                "password": "secret",
                "channel": 1,
                "stream_type": 0,
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert "secret" not in str(body)
        assert "admin" not in str(body)
        assert body["stream_id"]
        stopped = client.delete(f"/streams/{body['stream_id']}")
        assert stopped.status_code == 204


def test_probe_returns_503_when_runtime_missing():
    app = create_app(HikBridgeService(FakeSdk(False)))
    with TestClient(app) as client:
        response = client.post(
            "/probe",
            json={
                "host": "10.0.0.8",
                "port": 8000,
                "username": "admin",
                "password": "secret",
            },
        )
    assert response.status_code == 503
    assert "secret" not in response.text


def test_missing_stream_media_returns_404_before_streaming_starts():
    app = create_app(HikBridgeService(FakeSdk(True)))
    with TestClient(app) as client:
        response = client.get("/streams/not-found/media")
    assert response.status_code == 404
