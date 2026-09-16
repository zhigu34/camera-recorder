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
    """Compatibility URI resolver for all materialized media adapters.

    Manual RTSP and ONVIF return credentialed RTSP URIs. HIK SDK returns a
    backend-only HTTP proxy URI whose lifetime owns the HCNetSDK sidecar session.
    New code should prefer resolve_media_source when it needs transport metadata.
    """

    source = resolve_media_source(camera, purpose, preferred=preferred)
    if not source.uri:
        raise UnsupportedDeviceAdapter(
            f"media adapter {source.adapter} has no materialized URI; use resolve_media_source"
        )
    return ResolvedStream(uri=source.uri, role=source.role, purpose=source.purpose)
