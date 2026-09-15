from app.services.device_adapter import (
    ManualRtspDeviceAdapter,
    ResolvedStream,
    StreamPreference,
    StreamPurpose,
)


class UnsupportedDeviceAdapter(RuntimeError):
    pass


_manual_rtsp = ManualRtspDeviceAdapter()


def resolve_stream(
    camera,
    purpose: StreamPurpose,
    *,
    preferred: StreamPreference = "auto",
) -> ResolvedStream:
    connection_type = getattr(camera, "connection_type", "manual_rtsp")
    if connection_type == "manual_rtsp":
        return _manual_rtsp.resolve_stream(camera, purpose, preferred=preferred)
    raise UnsupportedDeviceAdapter(f"connection type {connection_type} is not implemented")
