from dataclasses import dataclass, field

from app.core.security import decrypt_secret
from app.services.media_source import MediaSource, StreamPreference, StreamPurpose, StreamRole


@dataclass(slots=True, frozen=True)
class HikBridgeTarget:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    channel: int = 1
    stream_type: int = 0


class HikMediaAdapter:
    def resolve_media_source(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> MediaSource:
        metadata = getattr(camera, "hik_metadata", None)
        if metadata is None:
            raise ValueError("HIK SDK metadata is missing; re-add or repair the camera")

        role: StreamRole
        if purpose == "recording" or preferred == "main":
            role = "main"
            stream_type = int(metadata.main_stream_type)
        else:
            role = "sub"
            stream_type = int(metadata.sub_stream_type)

        target = HikBridgeTarget(
            host=str(camera.ip),
            port=int(metadata.sdk_port),
            username=str(camera.username),
            password=decrypt_secret(str(camera.password_encrypted)),
            channel=int(metadata.channel),
            stream_type=stream_type,
        )
        return MediaSource(
            adapter="hik_sdk",
            transport="hik_bridge",
            role=role,
            purpose=purpose,
            bridge_target=target,
        )
