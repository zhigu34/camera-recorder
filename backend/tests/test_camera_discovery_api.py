import importlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.camera_discovery import (
    OnvifDiscoveryCandidate,
    OnvifDiscoveryResponse,
    RtspDiscoveryCandidate,
    RtspDiscoveryResponse,
)


def discovery_api():
    try:
        return importlib.import_module("app.api.camera_discovery")
    except ModuleNotFoundError:
        pytest.fail("camera discovery API is not implemented yet")


def test_onvif_discovery_api_proxies_typed_candidate(monkeypatch) -> None:
    module = discovery_api()

    async def fake_scan():
        return OnvifDiscoveryResponse(
            devices=[
                OnvifDiscoveryCandidate(
                    endpoint_reference="urn:uuid:camera-1",
                    xaddrs=["http://192.168.1.50/onvif/device_service"],
                    device_service_url="http://192.168.1.50/onvif/device_service",
                    host="192.168.1.50",
                    port=80,
                    selectable=True,
                )
            ],
            scan_duration_ms=10,
        )

    monkeypatch.setattr(module.discovery_client, "scan_onvif", fake_scan)

    with TestClient(app) as client:
        response = client.post("/api/camera-discovery/onvif")

    assert response.status_code == 200, response.text
    assert response.json()["devices"][0]["host"] == "192.168.1.50"


def test_rtsp_discovery_api_proxies_typed_candidate(monkeypatch) -> None:
    module = discovery_api()

    async def fake_scan():
        return RtspDiscoveryResponse(
            network="192.168.1.0/24",
            devices=[RtspDiscoveryCandidate(host="192.168.1.60")],
            scan_duration_ms=8,
        )

    monkeypatch.setattr(module.discovery_client, "scan_rtsp", fake_scan)

    with TestClient(app) as client:
        response = client.post("/api/camera-discovery/rtsp")

    assert response.status_code == 200, response.text
    assert response.json()["network"] == "192.168.1.0/24"
    assert response.json()["devices"] == [
        {"host": "192.168.1.60", "port": 554, "selectable": True}
    ]


def test_discovery_helper_unavailable_returns_503(monkeypatch) -> None:
    module = discovery_api()

    async def unavailable():
        raise module.CameraDiscoveryUnavailable("socket missing")

    monkeypatch.setattr(module.discovery_client, "scan_onvif", unavailable)

    with TestClient(app) as client:
        response = client.post("/api/camera-discovery/onvif")

    assert response.status_code == 503
    assert response.json()["detail"] == "ONVIF 局域网发现当前不可用"


def test_discovery_helper_invalid_response_returns_502(monkeypatch) -> None:
    module = discovery_api()

    async def invalid():
        raise module.CameraDiscoveryProtocolError("bad helper response")

    monkeypatch.setattr(module.discovery_client, "scan_rtsp", invalid)

    with TestClient(app) as client:
        response = client.post("/api/camera-discovery/rtsp")

    assert response.status_code == 502
    assert response.json()["detail"] == "RTSP 局域网发现返回了无效响应"
