from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from app.core.security import decrypt_secret
from app.models.camera import Camera
from app.schemas.camera import OnvifProbeResult
from app.schemas.camera_connection import (
    CameraAdapter,
    CameraConnectionCreate,
    CameraConnectionUpdate,
    HikConnectionCreate,
    HikConnectionUpdate,
    ManualRtspConnectionCreate,
    ManualRtspConnectionUpdate,
    OnvifConnectionCreate,
    OnvifConnectionUpdate,
)
from app.schemas.hikvision import HikProbeResult
from app.services.camera_connection import (
    upsert_hik_connection,
    upsert_manual_rtsp_connection,
    upsert_onvif_connection,
)
from app.services.camera_probe import CameraProbeError, build_rtsp_url, probe_stream_uri
from app.services.hik_bridge_client import HikBridgeClient, HikBridgeClientError
from app.services.hik_media_adapter import HikBridgeTarget
from app.services.onvif_client import OnvifClient, OnvifError, inject_uri_credentials


class CameraAdapterProbeError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        self.status_code = status_code
        super().__init__(message)


class CameraConnectionProbeResult(BaseModel):
    adapter: CameraAdapter
    ok: bool = True
    device: dict[str, Any]
    media: dict[str, Any]
    connection_cache: dict[str, Any]


def _strip_uri_credentials(uri: str | None) -> str | None:
    if not uri:
        return uri
    parsed = urlsplit(uri)
    if parsed.hostname is None:
        return uri
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _sanitize_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for profile in profiles:
        item = dict(profile)
        if "uri" in item:
            item["uri"] = _strip_uri_credentials(str(item["uri"])) if item["uri"] else item["uri"]
        sanitized.append(item)
    return sanitized


async def _probe_manual(
    draft: ManualRtspConnectionCreate | ManualRtspConnectionUpdate,
    *,
    password: str,
    rtsp_timeout_us: int,
) -> CameraConnectionProbeResult:
    try:
        media = await probe_stream_uri(
            stream_uri=build_rtsp_url(
                draft.host,
                draft.port,
                draft.username,
                password,
                draft.main_path,
            ),
            rtsp_timeout_us=rtsp_timeout_us,
        )
    except CameraProbeError as exc:
        raise CameraAdapterProbeError(str(exc)) from exc
    return CameraConnectionProbeResult(
        adapter="manual_rtsp",
        device={},
        media=media,
        connection_cache={
            "port": draft.port,
            "main_path": draft.main_path,
            "sub_path": draft.sub_path,
        },
    )


async def _probe_onvif(
    draft: OnvifConnectionCreate | OnvifConnectionUpdate,
    *,
    password: str,
    rtsp_timeout_us: int,
) -> CameraConnectionProbeResult:
    host = f"[{draft.host}]" if ":" in draft.host and not draft.host.startswith("[") else draft.host
    device_service_url = f"http://{host}:{draft.port}/onvif/device_service"
    client = OnvifClient(
        device_service_url=device_service_url,
        username=draft.username,
        password=password,
    )
    try:
        raw = await client.probe()
        discovered = OnvifProbeResult.model_validate(raw)
        media = await probe_stream_uri(
            stream_uri=inject_uri_credentials(
                discovered.recording_uri,
                draft.username,
                password,
            ),
            rtsp_timeout_us=rtsp_timeout_us,
        )
    except OnvifError as exc:
        raise CameraAdapterProbeError(str(exc)) from exc
    except CameraProbeError as exc:
        raise CameraAdapterProbeError(f"ONVIF device reachable but media validation failed: {exc}") from exc

    profiles = _sanitize_profiles([item.model_dump() for item in discovered.profiles])
    return CameraConnectionProbeResult(
        adapter="onvif",
        device={
            "manufacturer": discovered.manufacturer,
            "model": discovered.model,
            "firmware_version": discovered.firmware_version,
            "serial_number": discovered.serial_number,
            "hardware_id": discovered.hardware_id,
        },
        media=media,
        connection_cache={
            "device_service_url": discovered.device_service_url,
            "device_uuid": discovered.device_uuid,
            "capabilities": discovered.capabilities,
            "profiles": profiles,
            "recording_profile_token": discovered.recording_profile_token,
            "preview_profile_token": discovered.preview_profile_token,
            "detection_profile_token": discovered.detection_profile_token,
            "recording_uri": _strip_uri_credentials(discovered.recording_uri),
            "preview_uri": _strip_uri_credentials(discovered.preview_uri),
            "detection_uri": _strip_uri_credentials(discovered.detection_uri),
        },
    )


async def _probe_hik(
    draft: HikConnectionCreate | HikConnectionUpdate,
    *,
    password: str,
    rtsp_timeout_us: int,
) -> CameraConnectionProbeResult:
    client = HikBridgeClient()
    stream_id: str | None = None
    try:
        raw = await client.probe(
            host=draft.host,
            port=draft.sdk_port,
            username=draft.username,
            password=password,
        )
        discovered = HikProbeResult.model_validate({**dict(raw), "channel": draft.channel})
        stream_id = await client.create_stream(
            HikBridgeTarget(
                host=draft.host,
                port=draft.sdk_port,
                username=draft.username,
                password=password,
                channel=draft.channel,
                stream_type=draft.main_stream_type,
            )
        )
        media = await probe_stream_uri(
            stream_uri=client.media_url(stream_id),
            rtsp_timeout_us=rtsp_timeout_us,
        )
    except HikBridgeClientError as exc:
        status_code = exc.status_code if exc.status_code and 400 <= exc.status_code < 600 else 502
        raise CameraAdapterProbeError(str(exc), status_code=status_code) from exc
    except CameraProbeError as exc:
        raise CameraAdapterProbeError(f"HIK SDK login succeeded but media validation failed: {exc}") from exc
    finally:
        if stream_id:
            with suppress(Exception):
                await client.stop_stream(stream_id)

    device = discovered.model_dump(exclude={"ok", "channel"}, exclude_none=True)
    return CameraConnectionProbeResult(
        adapter="hik_sdk",
        device=device,
        media=media,
        connection_cache={
            "sdk_port": draft.sdk_port,
            "channel": draft.channel,
            "main_stream_type": draft.main_stream_type,
            "sub_stream_type": draft.sub_stream_type,
            "device_serial": discovered.serial_number,
            "device_model": discovered.device_model,
            "device_name": discovered.device_name,
        },
    )


async def probe_connection_draft(
    draft: CameraConnectionCreate | CameraConnectionUpdate,
    *,
    password: str,
    rtsp_timeout_us: int,
) -> CameraConnectionProbeResult:
    if isinstance(draft, (ManualRtspConnectionCreate, ManualRtspConnectionUpdate)):
        return await _probe_manual(draft, password=password, rtsp_timeout_us=rtsp_timeout_us)
    if isinstance(draft, (OnvifConnectionCreate, OnvifConnectionUpdate)):
        return await _probe_onvif(draft, password=password, rtsp_timeout_us=rtsp_timeout_us)
    if isinstance(draft, (HikConnectionCreate, HikConnectionUpdate)):
        return await _probe_hik(draft, password=password, rtsp_timeout_us=rtsp_timeout_us)
    raise CameraAdapterProbeError("unsupported camera adapter", status_code=422)


def _onvif_port(device_service_url: str) -> int:
    parsed = urlsplit(device_service_url)
    if parsed.port is not None:
        return parsed.port
    return 443 if parsed.scheme.lower() == "https" else 80


def _saved_connection_draft(camera: Camera) -> CameraConnectionUpdate:
    connection = camera.connection
    if connection is None:
        raise CameraAdapterProbeError("camera has no current connection", status_code=409)

    if connection.adapter == "manual_rtsp":
        config = connection.rtsp_config
        if config is None:
            raise CameraAdapterProbeError("manual RTSP connection config is missing", status_code=409)
        return ManualRtspConnectionUpdate(
            host=connection.host,
            username=connection.username,
            port=config.port,
            main_path=config.main_path,
            sub_path=config.sub_path,
        )
    if connection.adapter == "onvif":
        config = connection.onvif_config
        if config is None:
            raise CameraAdapterProbeError("ONVIF connection config is missing", status_code=409)
        return OnvifConnectionUpdate(
            host=connection.host,
            username=connection.username,
            port=_onvif_port(config.device_service_url),
        )
    if connection.adapter == "hik_sdk":
        config = connection.hik_config
        if config is None:
            raise CameraAdapterProbeError("HIK connection config is missing", status_code=409)
        return HikConnectionUpdate(
            host=connection.host,
            username=connection.username,
            sdk_port=config.sdk_port,
            channel=config.channel,
            main_stream_type=config.main_stream_type,
            sub_stream_type=config.sub_stream_type,
        )
    raise CameraAdapterProbeError("unsupported camera adapter", status_code=422)


async def probe_saved_connection(
    camera: Camera,
    *,
    rtsp_timeout_us: int,
) -> CameraConnectionProbeResult:
    connection = camera.connection
    if connection is None:
        raise CameraAdapterProbeError("camera has no current connection", status_code=409)
    try:
        password = decrypt_secret(connection.password_encrypted)
    except Exception as exc:
        raise CameraAdapterProbeError(
            "camera password cannot be decrypted; re-enter the password before probing",
            status_code=409,
        ) from exc
    return await probe_connection_draft(
        _saved_connection_draft(camera),
        password=password,
        rtsp_timeout_us=rtsp_timeout_us,
    )


def apply_probe_success(
    camera: Camera,
    result: CameraConnectionProbeResult,
    *,
    verified_at: datetime,
) -> None:
    connection = camera.connection
    if connection is None:
        raise CameraAdapterProbeError("camera has no current connection", status_code=409)
    if connection.adapter != result.adapter:
        raise CameraAdapterProbeError("probe result adapter does not match current connection", status_code=409)

    if result.adapter == "manual_rtsp":
        config = connection.rtsp_config
        if config is None:
            raise CameraAdapterProbeError("manual RTSP connection config is missing", status_code=409)
        upsert_manual_rtsp_connection(
            camera,
            host=connection.host,
            port=config.port,
            username=connection.username,
            password_encrypted=connection.password_encrypted,
            main_path=config.main_path,
            sub_path=config.sub_path,
            verification_status="verified",
            verified_at=verified_at,
            last_error=None,
        )
    elif result.adapter == "onvif":
        config = connection.onvif_config
        if config is None:
            raise CameraAdapterProbeError("ONVIF connection config is missing", status_code=409)
        cache = result.connection_cache
        upsert_onvif_connection(
            camera,
            host=connection.host,
            username=connection.username,
            password_encrypted=connection.password_encrypted,
            device_service_url=config.device_service_url,
            device_uuid=cache.get("device_uuid"),
            capabilities=cache.get("capabilities") or {},
            profiles=cache.get("profiles") or [],
            recording_profile_token=cache.get("recording_profile_token"),
            preview_profile_token=cache.get("preview_profile_token"),
            detection_profile_token=cache.get("detection_profile_token"),
            recording_uri=cache.get("recording_uri"),
            preview_uri=cache.get("preview_uri"),
            detection_uri=cache.get("detection_uri"),
            verification_status="verified",
            verified_at=verified_at,
            last_error=None,
        )
    else:
        config = connection.hik_config
        if config is None:
            raise CameraAdapterProbeError("HIK connection config is missing", status_code=409)
        cache = result.connection_cache
        upsert_hik_connection(
            camera,
            host=connection.host,
            username=connection.username,
            password_encrypted=connection.password_encrypted,
            sdk_port=config.sdk_port,
            channel=config.channel,
            main_stream_type=config.main_stream_type,
            sub_stream_type=config.sub_stream_type,
            device_serial=cache.get("device_serial"),
            device_model=cache.get("device_model"),
            device_name=cache.get("device_name"),
            verification_status="verified",
            verified_at=verified_at,
            last_error=None,
        )

    connection.verification_status = "verified"
    connection.verified_at = verified_at
    connection.last_error = None
    apply_probe_media(camera, result.media)


def apply_probe_failure(camera: Camera, error: str) -> None:
    connection = camera.connection
    if connection is None:
        raise CameraAdapterProbeError("camera has no current connection", status_code=409)
    connection.verification_status = "failed"
    connection.last_error = error


def apply_probe_media(camera: Camera, media: dict[str, Any]) -> None:
    for key in (
        "video_codec",
        "video_profile",
        "width",
        "height",
        "fps_num",
        "fps_den",
        "pixel_format",
        "has_b_frames",
        "video_time_base",
        "audio_codec",
        "audio_profile",
        "sample_rate",
        "channels",
        "audio_frame_samples",
    ):
        setattr(camera, key, media.get(key))
