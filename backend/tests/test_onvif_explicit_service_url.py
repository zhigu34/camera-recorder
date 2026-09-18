from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _onvif_connection(*, device_service_url: str) -> dict:
    return {
        "adapter": "onvif",
        "host": "192.0.2.80",
        "username": "operator",
        "password": "secret",
        "port": 8443,
        "device_service_url": device_service_url,
    }


def test_unified_create_preserves_explicit_onvif_device_service_url() -> None:
    explicit = "https://192.0.2.80:8443/custom/onvif/device"

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json={
                "name": "explicit-onvif-url",
                "enabled": False,
                "connection": _onvif_connection(device_service_url=explicit),
            },
        )

        assert created.status_code == 201, created.text
        body = created.json()
        camera_id = int(body["id"])
        assert body["connection"]["config"]["device_service_url"] == explicit

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


def test_unified_onvif_probe_uses_explicit_device_service_url(monkeypatch) -> None:
    from app.services import camera_adapter_probe

    explicit = "https://192.0.2.80:8443/custom/onvif/device"
    captured: list[str] = []

    class FakeOnvifClient:
        def __init__(
            self,
            *,
            device_service_url: str,
            username: str,
            password: str,
            timeout_seconds: float = 8.0,
        ) -> None:
            captured.append(device_service_url)
            assert username == "operator"
            assert password == "secret"
            assert timeout_seconds > 0

        async def probe(self):
            return {
                "manufacturer": "Example",
                "model": "Camera",
                "firmware_version": "1.0",
                "serial_number": "serial",
                "hardware_id": "hardware",
                "device_uuid": "uuid",
                "device_service_url": explicit,
                "capabilities": {
                    "media_xaddr": "http://192.0.2.80/onvif/media",
                    "events_xaddr": None,
                    "ptz_xaddr": None,
                },
                "profiles": [
                    {
                        "token": "main",
                        "name": "Main",
                        "encoding": "H264",
                        "width": 1920,
                        "height": 1080,
                        "fps": 25,
                        "uri": "rtsp://192.0.2.80/main",
                    }
                ],
                "recording_profile_token": "main",
                "preview_profile_token": "main",
                "detection_profile_token": "main",
                "recording_uri": "rtsp://192.0.2.80/main",
                "preview_uri": "rtsp://192.0.2.80/main",
                "detection_uri": "rtsp://192.0.2.80/main",
            }

    async def fake_probe_stream_uri(*, stream_uri: str, rtsp_timeout_us: int):
        assert stream_uri.startswith("rtsp://operator:secret@192.0.2.80/")
        assert rtsp_timeout_us > 0
        return {"video_codec": "h264", "width": 1920, "height": 1080}

    monkeypatch.setattr(camera_adapter_probe, "OnvifClient", FakeOnvifClient)
    monkeypatch.setattr(camera_adapter_probe, "probe_stream_uri", fake_probe_stream_uri)

    with TestClient(app) as client:
        response = client.post(
            "/api/camera-connections/probe",
            json={"connection": _onvif_connection(device_service_url=explicit)},
        )

    assert response.status_code == 200, response.text
    assert captured == [explicit]
    assert response.json()["connection_cache"]["device_service_url"] == explicit


def test_switch_to_onvif_preserves_explicit_device_service_url() -> None:
    explicit = "https://192.0.2.80:8443/custom/onvif/device"

    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json={
                "name": "switch-to-explicit-onvif",
                "enabled": False,
                "connection": {
                    "adapter": "manual_rtsp",
                    "host": "192.0.2.70",
                    "username": "viewer",
                    "password": "old-secret",
                    "port": 554,
                    "main_path": "/main",
                    "sub_path": None,
                },
            },
        )
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])

        switched = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "connection": _onvif_connection(device_service_url=explicit),
            },
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["connection"]["adapter"] == "onvif"
        assert switched.json()["connection"]["config"]["device_service_url"] == explicit

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204
