from types import SimpleNamespace

import pytest

from app.services.media_adapter import MediaAdapterRegistry, UnsupportedMediaAdapter
from app.services.media_source import MediaSource


class FakeAdapter:
    def __init__(self, name: str, transport: str = "rtsp") -> None:
        self.name = name
        self.transport = transport

    def resolve_media_source(self, camera, purpose, *, preferred="auto") -> MediaSource:
        if self.transport == "rtsp":
            return MediaSource(
                adapter=self.name,
                transport="rtsp",
                role="main",
                purpose=purpose,
                uri=f"rtsp://{camera.ip}/main",
            )
        return MediaSource(
            adapter=self.name,
            transport="hik_bridge",
            role="sub" if purpose != "recording" else "main",
            purpose=purpose,
            bridge_stream_id="opaque-session",
        )


def test_registry_selects_strictly_by_connection_type() -> None:
    registry = MediaAdapterRegistry()
    registry.register("manual_rtsp", FakeAdapter("manual_rtsp"))
    registry.register("onvif", FakeAdapter("onvif"))
    registry.register("hik_sdk", FakeAdapter("hik_sdk", transport="hik_bridge"))

    camera = SimpleNamespace(connection_type="hik_sdk", ip="10.0.0.9")
    source = registry.resolve(camera, "preview")

    assert source.adapter == "hik_sdk"
    assert source.transport == "hik_bridge"
    assert source.bridge_stream_id == "opaque-session"


def test_registry_prefers_current_connection_adapter_over_legacy_shadow() -> None:
    registry = MediaAdapterRegistry()
    registry.register("manual_rtsp", FakeAdapter("manual_rtsp"))
    registry.register("hik_sdk", FakeAdapter("hik_sdk", transport="hik_bridge"))

    camera = SimpleNamespace(
        connection_type="hik_sdk",
        ip="10.0.0.9",
        connection=SimpleNamespace(adapter="manual_rtsp"),
    )
    source = registry.resolve(camera, "preview")

    assert source.adapter == "manual_rtsp"
    assert source.transport == "rtsp"


def test_registry_never_falls_back_for_unknown_type() -> None:
    registry = MediaAdapterRegistry()
    registry.register("manual_rtsp", FakeAdapter("manual_rtsp"))

    with pytest.raises(UnsupportedMediaAdapter, match="future-protocol"):
        registry.resolve(SimpleNamespace(connection_type="future-protocol"), "recording")


def test_media_source_requires_transport_payload() -> None:
    with pytest.raises(ValueError, match="RTSP source requires uri"):
        MediaSource(
            adapter="manual_rtsp",
            transport="rtsp",
            role="main",
            purpose="recording",
        )

    with pytest.raises(ValueError, match="bridge source requires exactly one"):
        MediaSource(
            adapter="hik_sdk",
            transport="hik_bridge",
            role="main",
            purpose="recording",
        )


def test_media_source_rejects_mixed_transport_payloads() -> None:
    with pytest.raises(ValueError, match="must not include bridge_stream_id"):
        MediaSource(
            adapter="manual_rtsp",
            transport="rtsp",
            role="main",
            purpose="recording",
            uri="rtsp://camera/main",
            bridge_stream_id="unexpected",
        )
