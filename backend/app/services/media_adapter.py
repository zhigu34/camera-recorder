from typing import Protocol

from app.services.device_adapter import ManualRtspDeviceAdapter
from app.services.hik_media_adapter import HikMediaAdapter
from app.services.media_source import MediaSource, StreamPreference, StreamPurpose
from app.services.onvif_device_adapter import OnvifDeviceAdapter


class UnsupportedMediaAdapter(RuntimeError):
    pass


class MediaAdapter(Protocol):
    def resolve_media_source(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> MediaSource: ...


class MediaAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, MediaAdapter] = {}

    def register(self, connection_type: str, adapter: MediaAdapter) -> None:
        self._adapters[connection_type] = adapter

    def resolve(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> MediaSource:
        connection = getattr(camera, "connection", None)
        connection_type = (
            str(connection.adapter)
            if connection is not None
            else str(getattr(camera, "connection_type", "manual_rtsp"))
        )
        adapter = self._adapters.get(connection_type)
        if adapter is None:
            raise UnsupportedMediaAdapter(f"unsupported media adapter: {connection_type}")
        return adapter.resolve_media_source(camera, purpose, preferred=preferred)


_default_registry = MediaAdapterRegistry()
_default_registry.register("manual_rtsp", ManualRtspDeviceAdapter())
_default_registry.register("onvif", OnvifDeviceAdapter())
_default_registry.register("hik_sdk", HikMediaAdapter())


def register_media_adapter(connection_type: str, adapter: MediaAdapter) -> None:
    _default_registry.register(connection_type, adapter)


def resolve_media_source(
    camera,
    purpose: StreamPurpose,
    *,
    preferred: StreamPreference = "auto",
) -> MediaSource:
    return _default_registry.resolve(camera, purpose, preferred=preferred)
