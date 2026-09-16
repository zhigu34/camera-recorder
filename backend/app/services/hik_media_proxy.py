from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Literal

from app.core.security import decrypt_secret
from app.services.hik_media_adapter import HikBridgeTarget

HikStreamRole = Literal["main", "sub"]


def build_hik_target(camera, role: HikStreamRole) -> HikBridgeTarget:
    if str(getattr(camera, "connection_type", "")) != "hik_sdk":
        raise ValueError("camera is not configured for HIK SDK")
    metadata = getattr(camera, "hik_metadata", None)
    if metadata is None:
        raise ValueError("HIK SDK metadata is missing")
    stream_type = (
        int(metadata.main_stream_type)
        if role == "main"
        else int(metadata.sub_stream_type)
    )
    return HikBridgeTarget(
        host=str(camera.ip),
        port=int(metadata.sdk_port),
        username=str(camera.username),
        password=decrypt_secret(str(camera.password_encrypted)),
        channel=int(metadata.channel),
        stream_type=stream_type,
    )


async def iter_hik_stream(client, stream_id: str) -> AsyncIterator[bytes]:
    try:
        async for chunk in client.iter_media(stream_id):
            if chunk:
                yield chunk
    finally:
        with suppress(Exception):
            await client.stop_stream(stream_id)
