from app.services.device_adapter import ResolvedStream
from app.services.media_adapter import UnsupportedMediaAdapter, resolve_media_source
from app.services.media_source import StreamPreference, StreamPurpose


UnsupportedDeviceAdapter = UnsupportedMediaAdapter


def resolve_stream(
    camera,
    purpose: StreamPurpose,
    *,
    preferred: StreamPreference = "auto",
) -> ResolvedStream:
    source = resolve_media_source(camera, purpose, preferred=preferred)
    if source.transport != "rtsp" or not source.uri:
        raise UnsupportedDeviceAdapter(
            f"media adapter {source.adapter} does not expose a URI stream; use resolve_media_source"
        )
    return ResolvedStream(uri=source.uri, role=source.role, purpose=source.purpose)
