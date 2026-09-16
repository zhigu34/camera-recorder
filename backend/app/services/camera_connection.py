from __future__ import annotations

from datetime import datetime

from app.core.security import decrypt_secret
from app.models import Camera, CameraConnection, RtspConnectionConfig


class ConnectionAdapterMismatch(ValueError):
    """Raised when a write targets a different current adapter."""


def _same_encrypted_secret(current: str, candidate: str) -> bool:
    if current == candidate:
        return True
    try:
        return decrypt_secret(current) == decrypt_secret(candidate)
    except Exception:
        return False


def upsert_manual_rtsp_connection(
    camera: Camera,
    *,
    host: str,
    port: int,
    username: str,
    password_encrypted: str,
    main_path: str,
    sub_path: str | None,
    verification_status: str | None = None,
    verified_at: datetime | None = None,
    last_error: str | None = None,
) -> CameraConnection:
    normalized_sub_path = sub_path.strip() if sub_path else None
    connection = camera.connection
    effective_password_encrypted = password_encrypted

    if connection is None:
        connection = CameraConnection(
            adapter="manual_rtsp",
            host=host,
            username=username,
            password_encrypted=password_encrypted,
            revision=1,
            verification_status=verification_status or "unverified",
            verified_at=verified_at,
            last_error=last_error,
        )
        connection.rtsp_config = RtspConnectionConfig(
            port=port,
            main_path=main_path,
            sub_path=normalized_sub_path,
        )
        camera.connection = connection
    else:
        if connection.adapter != "manual_rtsp":
            raise ConnectionAdapterMismatch(
                f"current connection adapter is {connection.adapter}, expected manual_rtsp"
            )

        if _same_encrypted_secret(connection.password_encrypted, password_encrypted):
            effective_password_encrypted = connection.password_encrypted

        rtsp_config = connection.rtsp_config
        config_changed = rtsp_config is None or (
            connection.host != host
            or connection.username != username
            or connection.password_encrypted != effective_password_encrypted
            or rtsp_config.port != port
            or rtsp_config.main_path != main_path
            or rtsp_config.sub_path != normalized_sub_path
        )

        if rtsp_config is None:
            rtsp_config = RtspConnectionConfig()
            connection.rtsp_config = rtsp_config

        if config_changed:
            connection.revision += 1

        connection.host = host
        connection.username = username
        connection.password_encrypted = effective_password_encrypted
        rtsp_config.port = port
        rtsp_config.main_path = main_path
        rtsp_config.sub_path = normalized_sub_path

        if config_changed:
            connection.verification_status = verification_status or "unverified"
            connection.verified_at = verified_at
            connection.last_error = last_error
        else:
            if verification_status is not None:
                connection.verification_status = verification_status
            if verified_at is not None:
                connection.verified_at = verified_at
            if last_error is not None:
                connection.last_error = last_error

    # Rollback-window compatibility: the current connection is canonical, while
    # legacy Camera columns mirror it until the old read paths are retired.
    camera.connection_type = "manual_rtsp"
    camera.ip = host
    camera.rtsp_port = port
    camera.username = username
    camera.password_encrypted = effective_password_encrypted
    camera.rtsp_path = main_path
    camera.sub_rtsp_path = normalized_sub_path
    return connection
