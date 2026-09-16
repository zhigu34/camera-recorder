from dataclasses import dataclass
from typing import Protocol

from app.core.security import decrypt_secret
from app.services.camera_probe import build_rtsp_url
from app.services.media_source import MediaSource, StreamPreference, StreamPurpose, StreamRole


@dataclass(slots=True, frozen=True)
class ResolvedStream:
    uri: str
    role: StreamRole
    purpose: StreamPurpose


class DeviceAdapter(Protocol):
    def resolve_stream(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> ResolvedStream: ...


def infer_substream_path(main_path: str) -> str | None:
    if "/main" in main_path:
        prefix, suffix = main_path.rsplit("/main", 1)
        return f"{prefix}/sub{suffix}"
    if main_path.endswith("main"):
        return f"{main_path[:-4]}sub"
    return None


class ManualRtspDeviceAdapter:
    def resolve_media_source(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> MediaSource:
        main_path = str(camera.rtsp_path)
        configured_sub = str(camera.sub_rtsp_path).strip() if camera.sub_rtsp_path else None
        inferred_sub = infer_substream_path(main_path)

        role: StreamRole
        path: str
        if purpose == "recording" or preferred == "main":
            role, path = "main", main_path
        elif preferred == "sub":
            selected = configured_sub or inferred_sub
            if not selected:
                raise ValueError("sub stream is not configured and cannot be inferred")
            role, path = "sub", selected
        else:
            selected = configured_sub or inferred_sub
            if selected:
                role, path = "sub", selected
            else:
                role, path = "main", main_path

        uri = build_rtsp_url(
            str(camera.ip),
            int(camera.rtsp_port),
            str(camera.username),
            decrypt_secret(str(camera.password_encrypted)),
            path,
        )
        return MediaSource(
            adapter="manual_rtsp",
            transport="rtsp",
            uri=uri,
            role=role,
            purpose=purpose,
        )

    def resolve_stream(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> ResolvedStream:
        source = self.resolve_media_source(camera, purpose, preferred=preferred)
        assert source.uri is not None
        return ResolvedStream(uri=source.uri, role=source.role, purpose=source.purpose)


ManualRtspMediaAdapter = ManualRtspDeviceAdapter
