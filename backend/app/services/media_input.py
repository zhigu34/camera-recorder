from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from app.services.hik_bridge_client import HikBridgeClient
from app.services.media_source import MediaSource


@dataclass(slots=True, frozen=True)
class MediaInput:
    transport_args: tuple[str, ...]
    uri: str


@dataclass(slots=True)
class MediaInputLease:
    input: MediaInput
    _cleanup: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._cleanup is not None:
            await self._cleanup()

    async def __aenter__(self) -> "MediaInputLease":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


def media_input_from_uri(uri: str, *, timeout_us: int) -> MediaInput:
    scheme = urlsplit(uri).scheme.lower()
    if scheme == "rtsp":
        return MediaInput(
            transport_args=(
                "-rtsp_transport",
                "tcp",
                "-timeout",
                str(timeout_us),
            ),
            uri=uri,
        )
    if scheme in {"http", "https"}:
        return MediaInput(
            transport_args=("-rw_timeout", str(timeout_us)),
            uri=uri,
        )
    raise ValueError(f"unsupported media input URI scheme: {scheme or '<empty>'}")


async def open_media_input(
    source: MediaSource,
    *,
    rtsp_timeout_us: int,
    bridge_client: Any | None = None,
) -> MediaInputLease:
    if source.uri:
        return MediaInputLease(
            media_input_from_uri(source.uri, timeout_us=rtsp_timeout_us)
        )

    if source.transport != "hik_bridge":
        raise ValueError(f"unsupported media transport: {source.transport}")

    client = bridge_client or HikBridgeClient()
    stream_id = source.bridge_stream_id
    owns_stream = False
    if not stream_id:
        if source.bridge_target is None:
            raise ValueError("HIK bridge media source has no target")
        stream_id = await client.create_stream(source.bridge_target)
        owns_stream = True
    media_url = client.media_url(stream_id)

    async def cleanup() -> None:
        if owns_stream:
            await client.stop_stream(stream_id)

    return MediaInputLease(
        media_input_from_uri(media_url, timeout_us=rtsp_timeout_us),
        _cleanup=cleanup,
    )
