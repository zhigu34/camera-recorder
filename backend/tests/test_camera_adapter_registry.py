import pytest

from app.core.config import Settings
from app.services.hik_bridge_client import HikBridgeClientError


def _by_id(values):
    return {item.id: item for item in values}


def test_hik_deployment_flag_defaults_to_disabled() -> None:
    assert Settings.model_fields["hik_enabled"].default is False


@pytest.mark.asyncio
async def test_adapter_registry_skips_bridge_health_when_hik_is_disabled(monkeypatch) -> None:
    from app.services import camera_adapter_registry as registry

    bridge_constructions = 0

    def unexpected_bridge():
        nonlocal bridge_constructions
        bridge_constructions += 1
        raise AssertionError("disabled HIK must not construct a bridge client")

    monkeypatch.setattr(registry.settings, "hik_enabled", False, raising=False)
    monkeypatch.setattr(registry, "HikBridgeClient", unexpected_bridge)

    values = _by_id(await registry.list_camera_adapter_capabilities())

    assert set(values) == {"manual_rtsp", "onvif", "hik_sdk"}
    assert values["manual_rtsp"].available is True
    assert values["onvif"].available is True
    assert values["hik_sdk"].available is False
    assert (
        values["hik_sdk"].unavailable_reason
        == "HIK SDK adapter is disabled by deployment configuration"
    )
    assert bridge_constructions == 0


@pytest.mark.asyncio
async def test_adapter_registry_reports_hik_available_only_with_runtime(monkeypatch) -> None:
    from app.services import camera_adapter_registry as registry

    health_calls = 0

    class HealthyBridge:
        async def health(self):
            nonlocal health_calls
            health_calls += 1
            return {"ok": True, "runtime_available": True}

    monkeypatch.setattr(registry.settings, "hik_enabled", True, raising=False)
    monkeypatch.setattr(registry, "HikBridgeClient", lambda: HealthyBridge())

    values = _by_id(await registry.list_camera_adapter_capabilities())

    assert values["hik_sdk"].available is True
    assert values["hik_sdk"].unavailable_reason is None
    assert health_calls == 1


@pytest.mark.asyncio
async def test_adapter_registry_keeps_hik_unavailable_when_runtime_is_missing(monkeypatch) -> None:
    from app.services import camera_adapter_registry as registry

    class NoRuntimeBridge:
        async def health(self):
            return {"ok": True, "runtime_available": False}

    monkeypatch.setattr(registry.settings, "hik_enabled", True, raising=False)
    monkeypatch.setattr(registry, "HikBridgeClient", lambda: NoRuntimeBridge())

    values = _by_id(await registry.list_camera_adapter_capabilities())

    assert values["hik_sdk"].available is False
    assert values["hik_sdk"].unavailable_reason is not None
    assert "runtime" in values["hik_sdk"].unavailable_reason.lower()


@pytest.mark.asyncio
async def test_adapter_registry_keeps_hik_visible_when_bridge_is_unavailable(monkeypatch) -> None:
    from app.services import camera_adapter_registry as registry

    class UnhealthyBridge:
        async def health(self):
            raise HikBridgeClientError("bridge offline")

    monkeypatch.setattr(registry.settings, "hik_enabled", True, raising=False)
    monkeypatch.setattr(registry, "HikBridgeClient", lambda: UnhealthyBridge())

    values = _by_id(await registry.list_camera_adapter_capabilities())

    assert set(values) == {"manual_rtsp", "onvif", "hik_sdk"}
    assert values["hik_sdk"].available is False
    assert values["hik_sdk"].unavailable_reason == "bridge offline"
