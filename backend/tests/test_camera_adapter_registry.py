import pytest

from app.services.hik_bridge_client import HikBridgeClientError


def _by_id(values):
    return {item.id: item for item in values}


@pytest.mark.asyncio
async def test_adapter_registry_reports_all_supported_adapters_when_hik_is_healthy(monkeypatch) -> None:
    from app.services import camera_adapter_registry as registry

    class HealthyBridge:
        async def health(self):
            return {"status": "ok"}

    monkeypatch.setattr(registry, "HikBridgeClient", lambda: HealthyBridge())

    values = _by_id(await registry.list_camera_adapter_capabilities())
    assert set(values) == {"manual_rtsp", "onvif", "hik_sdk"}
    assert values["manual_rtsp"].available is True
    assert values["onvif"].available is True
    assert values["hik_sdk"].available is True
    assert values["hik_sdk"].unavailable_reason is None


@pytest.mark.asyncio
async def test_adapter_registry_keeps_hik_visible_when_bridge_is_unavailable(monkeypatch) -> None:
    from app.services import camera_adapter_registry as registry

    class UnhealthyBridge:
        async def health(self):
            raise HikBridgeClientError("bridge offline")

    monkeypatch.setattr(registry, "HikBridgeClient", lambda: UnhealthyBridge())

    values = _by_id(await registry.list_camera_adapter_capabilities())
    assert set(values) == {"manual_rtsp", "onvif", "hik_sdk"}
    assert values["hik_sdk"].available is False
    assert values["hik_sdk"].unavailable_reason == "bridge offline"
