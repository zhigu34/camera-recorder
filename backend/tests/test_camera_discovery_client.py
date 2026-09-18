import asyncio

import httpx
import pytest

from app.services.camera_discovery_client import (
    CameraDiscoveryClient,
    CameraDiscoveryUnavailable,
)


class _SlowClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, path: str, json: dict):
        assert path == "/scan/onvif"
        assert json == {}
        await asyncio.sleep(0.05)
        raise AssertionError("overall timeout should cancel the request first")


class _BrokenClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, path: str, json: dict):
        raise httpx.ReadError("helper disconnected")


@pytest.mark.asyncio
async def test_discovery_client_enforces_overall_deadline(monkeypatch) -> None:
    from app.services import camera_discovery_client as module

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_kwargs: _SlowClient())
    client = CameraDiscoveryClient("/tmp/discovery.sock", timeout_seconds=0.01)

    with pytest.raises(CameraDiscoveryUnavailable):
        await client.scan_onvif()


@pytest.mark.asyncio
async def test_discovery_client_maps_transport_errors_to_unavailable(monkeypatch) -> None:
    from app.services import camera_discovery_client as module

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_kwargs: _BrokenClient())
    client = CameraDiscoveryClient("/tmp/discovery.sock", timeout_seconds=0.1)

    with pytest.raises(CameraDiscoveryUnavailable):
        await client.scan_onvif()
