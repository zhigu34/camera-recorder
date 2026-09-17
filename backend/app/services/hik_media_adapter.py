from dataclasses import dataclass, field

from app.core.config import settings
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
        connection = getattr(camera, "connection", None)
        if connection is not None:
            if str(connection.adapter) != "hik_sdk":
                raise ValueError(
                    f"current connection adapter is {connection.adapter}, expected hik_sdk"
                )
            if getattr(connection, "hik_config", None) is None:
                raise ValueError("HIK current connection config is missing")
        elif getattr(camera, "hik_metadata", None) is None:
            raise ValueError("HIK SDK metadata is missing; re-add or repair the camera")

        role: StreamRole
        if purpose == "recording" or preferred == "main":
            role = "main"
        else:
            role = "sub"

        # Keep HCNetSDK credentials out of every FFmpeg command. The backend-only
        # proxy loads credentials from SQLite, creates a sidecar session for the
        # duration of the HTTP consumer, and tears the SDK session down on disconnect.
        base = settings.internal_media_url.rstrip("/")
        uri = f"{base}/internal/hik-media/{int(camera.id)}/{role}"
        return MediaSource(
            adapter="hik_sdk",
            transport="hik_bridge",
            role=role,
            purpose=purpose,
            uri=uri,
        )
