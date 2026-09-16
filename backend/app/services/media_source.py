from dataclasses import dataclass, field
from typing import Any, Literal

StreamRole = Literal["main", "sub"]
StreamPurpose = Literal["recording", "preview", "detection"]
StreamPreference = Literal["auto", "main", "sub"]
MediaTransport = Literal["rtsp", "hik_bridge"]


@dataclass(slots=True, frozen=True)
class MediaSource:
    adapter: str
    transport: MediaTransport
    role: StreamRole
    purpose: StreamPurpose
    uri: str | None = None
    bridge_stream_id: str | None = None
    # Keep credentials out of repr/logging, but include the target in equality so
    # an IP, channel, stream-type, username, or password change restarts workers.
    bridge_target: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.transport == "rtsp":
            if not self.uri:
                raise ValueError("RTSP source requires uri")
            if self.bridge_stream_id is not None or self.bridge_target is not None:
                raise ValueError("RTSP source must not include bridge_stream_id or bridge_target")
            return
        if self.transport == "hik_bridge":
            variants = sum(
                value is not None
                for value in (self.uri, self.bridge_stream_id, self.bridge_target)
            )
            if variants != 1:
                raise ValueError(
                    "bridge source requires exactly one of uri, bridge_stream_id, or bridge_target"
                )
            return
        raise ValueError(f"unsupported media transport: {self.transport}")
