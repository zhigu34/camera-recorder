from types import SimpleNamespace

import pytest

from app.models.motion import MotionDetectionSettings
from app.models.onvif_events import OnvifEventSettings
from app.services.event_detection import event_source_registry
from app.services.event_detection.registry import EventSourceConflict


def _onvif_camera(*, verified: bool = True, events_xaddr: str | None = "http://192.0.2.90/onvif/events"):
    config = SimpleNamespace(
        capabilities_json={
            "events_xaddr": events_xaddr,
            "event_types": ["motion", "person"],
            "event_topics": ["RuleEngine/CellMotionDetector/Motion"],
        }
    )
    connection = SimpleNamespace(
        adapter="onvif",
        verification_status="verified" if verified else "unverified",
        onvif_config=config,
    )
    return SimpleNamespace(id=90, enabled=True, connection=connection)


@pytest.mark.asyncio
async def test_onvif_source_descriptor_uses_persisted_event_capabilities() -> None:
    adapter = event_source_registry.get("camera.onvif")
    descriptor = await adapter.descriptor(_onvif_camera(), None)

    assert descriptor.id == "camera.onvif"
    assert descriptor.source_kind == "camera_native"
    assert descriptor.provider == "onvif"
    assert descriptor.status == "available"
    assert descriptor.capabilities == ["motion", "person"]
    assert descriptor.configurable is True


@pytest.mark.asyncio
async def test_onvif_source_is_unsupported_without_events_service() -> None:
    adapter = event_source_registry.get("camera.onvif")
    descriptor = await adapter.descriptor(_onvif_camera(events_xaddr=None), None)

    assert descriptor.status == "unsupported"
    assert descriptor.capabilities == []


@pytest.mark.asyncio
async def test_enabling_onvif_source_rejects_enabled_local_motion(monkeypatch) -> None:
    adapter = event_source_registry.get("camera.onvif")
    camera = _onvif_camera()

    class FakeDb:
        async def get(self, model, key):
            if model is MotionDetectionSettings:
                return SimpleNamespace(enabled=True)
            if model is OnvifEventSettings:
                return None
            raise AssertionError(model)

    with pytest.raises(EventSourceConflict, match="local.motion"):
        await adapter.update(camera, {"enabled": True}, FakeDb())


@pytest.mark.asyncio
async def test_enabling_local_motion_rejects_enabled_onvif_source(monkeypatch) -> None:
    adapter = event_source_registry.get("local.motion")
    camera = SimpleNamespace(id=90)

    class FakeDb:
        async def get(self, model, key):
            if model is OnvifEventSettings:
                return SimpleNamespace(enabled=True)
            raise AssertionError(model)

    monkeypatch.setattr(
        "app.services.event_detection.motion_source.update_motion_detection_settings",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(EventSourceConflict, match="camera.onvif"):
        await adapter.update(
            camera,
            {
                "enabled": True,
                "sensitivity": "medium",
                "analysis_fps": 5,
                "analysis_width": 640,
                "min_duration_ms": 800,
                "merge_gap_ms": 10000,
                "event_min_interval_ms": 60000,
            },
            FakeDb(),
        )
