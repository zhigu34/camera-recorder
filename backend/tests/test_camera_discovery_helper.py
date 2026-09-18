import importlib

import pytest
from fastapi.testclient import TestClient


def helper_module():
    try:
        return importlib.import_module("app.discovery_helper")
    except ModuleNotFoundError:
        pytest.fail("camera discovery helper is not implemented yet")


def test_discovery_helper_health_does_not_trigger_scan() -> None:
    module = helper_module()
    with TestClient(module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_discovery_helper_proxies_onvif_scan_without_credentials(monkeypatch) -> None:
    module = helper_module()

    async def fake_scan_onvif():
        return {
            "devices": [
                {
                    "endpoint_reference": "urn:uuid:camera-1",
                    "xaddrs": ["http://192.168.1.50/onvif/device_service"],
                    "scopes": [],
                    "device_service_url": "http://192.168.1.50/onvif/device_service",
                    "host": "192.168.1.50",
                    "port": 80,
                    "selectable": True,
                    "unavailable_reason": None,
                }
            ],
            "scan_duration_ms": 15,
            "warnings": [],
        }

    monkeypatch.setattr(module, "_scan_onvif", fake_scan_onvif)

    with TestClient(module.app) as client:
        response = client.post("/scan/onvif", json={})

    assert response.status_code == 200
    assert response.json()["devices"][0]["host"] == "192.168.1.50"
    assert "username" not in response.text
    assert "password" not in response.text


def test_discovery_helper_proxies_rtsp_scan_without_credentials(monkeypatch) -> None:
    module = helper_module()

    async def fake_scan_rtsp():
        return {
            "network": "192.168.1.0/24",
            "devices": [{"host": "192.168.1.60", "port": 554, "selectable": True}],
            "scan_duration_ms": 22,
            "warnings": [],
        }

    monkeypatch.setattr(module, "_scan_rtsp", fake_scan_rtsp)

    with TestClient(module.app) as client:
        response = client.post("/scan/rtsp", json={})

    assert response.status_code == 200
    assert response.json() == {
        "network": "192.168.1.0/24",
        "devices": [{"host": "192.168.1.60", "port": 554, "selectable": True}],
        "scan_duration_ms": 22,
        "warnings": [],
    }
