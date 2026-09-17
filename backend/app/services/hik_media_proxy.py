from collections.abc import AsyncIterator

from app.core.security import decrypt_secret
from app.services.hik_bridge_client import HikBridgeClient
from app.services.hik_media_adapter import HikBridgeTarget, HikStreamRole


def build_hik_target(camera, role: HikStreamRole) -> HikBridgeTarget:
    connection = getattr(camera, "connection", None)
    if connection is not None:
        if str(connection.adapter) != "hik_sdk":
            raise ValueError(
                f"current connection adapter is {connection.adapter}, expected hik_sdk"
            )
        metadata = getattr(connection, "hik_config", None)
        if metadata is None:
            raise ValueError("HIK current connection config is missing")
        host = str(connection.host)
        username = str(connection.username)
        password_encrypted = str(connection.password_encrypted)
    else:
        if str(getattr(camera, "connection_type", "")) != "hik_sdk":
            raise ValueError("camera is not configured for HIK SDK")
        metadata = getattr(camera, "hik_metadata", None)
        if metadata is None:
            raise ValueError("HIK SDK metadata is missing; re-add or repair the camera")
        host = str(camera.ip)
        username = str(camera.username)
        password_encrypted = str(camera.password_encrypted)

    stream_type = metadata.main_stream_type if role == "main" else metadata.sub_stream_type
    return HikBridgeTarget(
        host=host,
        port=int(metadata.sdk_port),
        username=username,
        password=decrypt_secret(password_encrypted),
        channel=int(metadata.channel),
        stream_type=int(stream_type),
    )


async def iter_hik_stream(
    client: HikBridgeClient,
    stream_id: str,
) -> AsyncIterator[bytes]:
    try:
        async for chunk in client.iter_media(stream_id):
            yield chunk
    finally:
        await client.stop_stream(stream_id)
