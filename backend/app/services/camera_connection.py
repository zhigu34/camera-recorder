from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from app.core.security import decrypt_secret
from app.models import (
    Camera,
    CameraConnection,
    HikConnectionConfig,
    HikDeviceMetadata,
    OnvifConnectionConfig,
    RtspConnectionConfig,
)


class ConnectionAdapterMismatch(ValueError):
    """Raised when a write targets a different current adapter."""


def _same_encrypted_secret(current: str, candidate: str) -> bool:
    if current == candidate:
        return True
    try:
        return decrypt_secret(current) == decrypt_secret(candidate)
    except Exception:
        return False


def _credential_free_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if not parsed.hostname:
        return uri
    host = parsed.hostname
    authority = f"[{host}]" if ":" in host else host
    if parsed.port is not None:
        authority = f"{authority}:{parsed.port}"
    return urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, parsed.fragment))


def _rtsp_shadow_fields(uri: str, fallback_host: str) -> tuple[str, int, str]:
    parsed = urlsplit(uri)
    host = parsed.hostname or fallback_host
    port = parsed.port or 554
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return host, port, path


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

    camera.connection_type = "manual_rtsp"
    camera.ip = host
    camera.rtsp_port = port
    camera.username = username
    camera.password_encrypted = effective_password_encrypted
    camera.rtsp_path = main_path
    camera.sub_rtsp_path = normalized_sub_path
    return connection


def upsert_onvif_connection(
    camera: Camera,
    *,
    host: str,
    username: str,
    password_encrypted: str,
    device_service_url: str,
    device_uuid: str | None,
    capabilities: dict,
    profiles: list[dict],
    recording_profile_token: str,
    preview_profile_token: str | None,
    detection_profile_token: str | None,
    recording_uri: str,
    preview_uri: str | None,
    detection_uri: str | None,
    verified_at: datetime,
) -> CameraConnection:
    safe_recording_uri = _credential_free_uri(recording_uri)
    safe_preview_uri = _credential_free_uri(preview_uri) if preview_uri else None
    safe_detection_uri = _credential_free_uri(detection_uri) if detection_uri else None
    connection = camera.connection
    effective_password_encrypted = password_encrypted

    if connection is None:
        connection = CameraConnection(
            adapter="onvif",
            host=host,
            username=username,
            password_encrypted=password_encrypted,
            revision=1,
            verification_status="verified",
            verified_at=verified_at,
            last_error=None,
        )
        connection.onvif_config = OnvifConnectionConfig(
            device_service_url=device_service_url,
            device_uuid=device_uuid,
            capabilities_json=capabilities,
            profiles_json=profiles,
            recording_profile_token=recording_profile_token,
            preview_profile_token=preview_profile_token,
            detection_profile_token=detection_profile_token,
            recording_uri=safe_recording_uri,
            preview_uri=safe_preview_uri,
            detection_uri=safe_detection_uri,
        )
        camera.connection = connection
    else:
        if connection.adapter != "onvif":
            raise ConnectionAdapterMismatch(
                f"current connection adapter is {connection.adapter}, expected onvif"
            )
        if _same_encrypted_secret(connection.password_encrypted, password_encrypted):
            effective_password_encrypted = connection.password_encrypted

        config = connection.onvif_config
        config_changed = config is None or (
            connection.host != host
            or connection.username != username
            or connection.password_encrypted != effective_password_encrypted
            or config.device_service_url != device_service_url
            or config.device_uuid != device_uuid
            or config.capabilities_json != capabilities
            or config.profiles_json != profiles
            or config.recording_profile_token != recording_profile_token
            or config.preview_profile_token != preview_profile_token
            or config.detection_profile_token != detection_profile_token
            or config.recording_uri != safe_recording_uri
            or config.preview_uri != safe_preview_uri
            or config.detection_uri != safe_detection_uri
        )
        if config is None:
            config = OnvifConnectionConfig()
            connection.onvif_config = config
        if config_changed:
            connection.revision += 1

        connection.host = host
        connection.username = username
        connection.password_encrypted = effective_password_encrypted
        connection.verification_status = "verified"
        connection.verified_at = verified_at
        connection.last_error = None
        config.device_service_url = device_service_url
        config.device_uuid = device_uuid
        config.capabilities_json = capabilities
        config.profiles_json = profiles
        config.recording_profile_token = recording_profile_token
        config.preview_profile_token = preview_profile_token
        config.detection_profile_token = detection_profile_token
        config.recording_uri = safe_recording_uri
        config.preview_uri = safe_preview_uri
        config.detection_uri = safe_detection_uri

    legacy_host, legacy_port, legacy_main_path = _rtsp_shadow_fields(
        safe_recording_uri,
        host,
    )
    legacy_sub_path = None
    if safe_preview_uri and preview_profile_token != recording_profile_token:
        _preview_host, _preview_port, legacy_sub_path = _rtsp_shadow_fields(
            safe_preview_uri,
            host,
        )

    camera.connection_type = "onvif"
    camera.ip = legacy_host
    camera.rtsp_port = legacy_port
    camera.username = username
    camera.password_encrypted = effective_password_encrypted
    camera.rtsp_path = legacy_main_path
    camera.sub_rtsp_path = legacy_sub_path
    return connection


def upsert_hik_connection(
    camera: Camera,
    *,
    host: str,
    username: str,
    password_encrypted: str,
    sdk_port: int,
    channel: int,
    main_stream_type: int,
    sub_stream_type: int,
    device_serial: str | None,
    device_model: str | None,
    device_name: str | None,
    verified_at: datetime,
) -> CameraConnection:
    connection = camera.connection
    effective_password_encrypted = password_encrypted

    if connection is None:
        connection = CameraConnection(
            adapter="hik_sdk",
            host=host,
            username=username,
            password_encrypted=password_encrypted,
            revision=1,
            verification_status="verified",
            verified_at=verified_at,
            last_error=None,
        )
        connection.hik_config = HikConnectionConfig(
            sdk_port=sdk_port,
            channel=channel,
            main_stream_type=main_stream_type,
            sub_stream_type=sub_stream_type,
            device_serial=device_serial,
            device_model=device_model,
            device_name=device_name,
        )
        camera.connection = connection
    else:
        if connection.adapter != "hik_sdk":
            raise ConnectionAdapterMismatch(
                f"current connection adapter is {connection.adapter}, expected hik_sdk"
            )
        if _same_encrypted_secret(connection.password_encrypted, password_encrypted):
            effective_password_encrypted = connection.password_encrypted

        config = connection.hik_config
        config_changed = config is None or (
            connection.host != host
            or connection.username != username
            or connection.password_encrypted != effective_password_encrypted
            or config.sdk_port != sdk_port
            or config.channel != channel
            or config.main_stream_type != main_stream_type
            or config.sub_stream_type != sub_stream_type
            or config.device_serial != device_serial
            or config.device_model != device_model
            or config.device_name != device_name
        )
        if config is None:
            config = HikConnectionConfig()
            connection.hik_config = config
        if config_changed:
            connection.revision += 1

        connection.host = host
        connection.username = username
        connection.password_encrypted = effective_password_encrypted
        connection.verification_status = "verified"
        connection.verified_at = verified_at
        connection.last_error = None
        config.sdk_port = sdk_port
        config.channel = channel
        config.main_stream_type = main_stream_type
        config.sub_stream_type = sub_stream_type
        config.device_serial = device_serial
        config.device_model = device_model
        config.device_name = device_name

    camera.connection_type = "hik_sdk"
    camera.ip = host
    camera.rtsp_port = 554
    camera.username = username
    camera.password_encrypted = effective_password_encrypted
    camera.rtsp_path = "/hik-sdk/main"
    camera.sub_rtsp_path = "/hik-sdk/sub"

    metadata = camera.hik_metadata
    if metadata is None:
        metadata = HikDeviceMetadata()
        camera.hik_metadata = metadata
    metadata.sdk_port = sdk_port
    metadata.channel = channel
    metadata.main_stream_type = main_stream_type
    metadata.sub_stream_type = sub_stream_type
    metadata.device_serial = device_serial
    metadata.device_model = device_model
    metadata.device_name = device_name
    return connection


def _prepare_connection_switch(camera: Camera, target_adapter: str) -> CameraConnection:
    connection = camera.connection
    if connection is None:
        raise ValueError("camera has no current connection to switch")
    if connection.adapter == target_adapter:
        raise ConnectionAdapterMismatch(
            f"current connection adapter is already {target_adapter}; use the strict upsert"
        )

    connection.rtsp_config = None
    connection.onvif_config = None
    connection.hik_config = None
    connection.adapter = target_adapter
    return connection


def switch_to_manual_rtsp_connection(
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
    _prepare_connection_switch(camera, "manual_rtsp")
    return upsert_manual_rtsp_connection(
        camera,
        host=host,
        port=port,
        username=username,
        password_encrypted=password_encrypted,
        main_path=main_path,
        sub_path=sub_path,
        verification_status=verification_status,
        verified_at=verified_at,
        last_error=last_error,
    )


def switch_to_onvif_connection(
    camera: Camera,
    *,
    host: str,
    username: str,
    password_encrypted: str,
    device_service_url: str,
    device_uuid: str | None,
    capabilities: dict,
    profiles: list[dict],
    recording_profile_token: str,
    preview_profile_token: str | None,
    detection_profile_token: str | None,
    recording_uri: str,
    preview_uri: str | None,
    detection_uri: str | None,
    verified_at: datetime,
) -> CameraConnection:
    _prepare_connection_switch(camera, "onvif")
    return upsert_onvif_connection(
        camera,
        host=host,
        username=username,
        password_encrypted=password_encrypted,
        device_service_url=device_service_url,
        device_uuid=device_uuid,
        capabilities=capabilities,
        profiles=profiles,
        recording_profile_token=recording_profile_token,
        preview_profile_token=preview_profile_token,
        detection_profile_token=detection_profile_token,
        recording_uri=recording_uri,
        preview_uri=preview_uri,
        detection_uri=detection_uri,
        verified_at=verified_at,
    )


def switch_to_hik_connection(
    camera: Camera,
    *,
    host: str,
    username: str,
    password_encrypted: str,
    sdk_port: int,
    channel: int,
    main_stream_type: int,
    sub_stream_type: int,
    device_serial: str | None,
    device_model: str | None,
    device_name: str | None,
    verified_at: datetime,
) -> CameraConnection:
    _prepare_connection_switch(camera, "hik_sdk")
    return upsert_hik_connection(
        camera,
        host=host,
        username=username,
        password_encrypted=password_encrypted,
        sdk_port=sdk_port,
        channel=channel,
        main_stream_type=main_stream_type,
        sub_stream_type=sub_stream_type,
        device_serial=device_serial,
        device_model=device_model,
        device_name=device_name,
        verified_at=verified_at,
    )
