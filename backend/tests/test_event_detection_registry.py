from types import SimpleNamespace

import pytest

from app.services.event_detection import event_source_registry
from app.services.event_detection.registry import EventSourceRegistry, UnknownEventSource


def test_default_registry_contains_only_local_motion() -> None:
    assert event_source_registry.ids() == ["local.motion"]


@pytest.mark.asyncio
async def test_motion_descriptor_is_honest_local_motion_provider() -> None:
    adapter = event_source_registry.get("local.motion")
    descriptor = await adapter.descriptor(SimpleNamespace(id=1), None)

    assert descriptor.id == "local.motion"
    assert descriptor.source_kind == "local"
    assert descriptor.provider == "motion"
    assert descriptor.capabilities == ["motion"]
    assert descriptor.configurable is True
    assert descriptor.status == "available"


def test_registry_rejects_duplicate_source_ids() -> None:
    class FakeAdapter:
        source_id = "local.motion"

    registry = EventSourceRegistry()
    registry.register(FakeAdapter())
    with pytest.raises(ValueError, match="duplicate event source"):
        registry.register(FakeAdapter())


def test_registry_raises_typed_error_for_unknown_source() -> None:
    with pytest.raises(UnknownEventSource):
        EventSourceRegistry().get("camera.onvif")
