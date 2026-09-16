from datetime import datetime, timezone
from fractions import Fraction
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import encrypt_secret
from app.models.camera import Camera
from app.models.onvif import OnvifDeviceMetadata
from app.schemas.camera import (
    CameraRead,
    OnvifCameraCreate,
    OnvifCameraUpdate,
    OnvifProbeRequest,
    OnvifProbeResult,
)
from app.services.camera_config import runtime_config
from app.services.camera_identity import infer_camera_form_factor
from app.services.camera_probe import CameraProbeError, probe_stream_uri
from app.services.event_log import add_audit_event, add_event
from app.services.motion_manager import motion_detection_manager
from app.services.onvif_client import OnvifClient, OnvifError, inject_uri_credentials
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule_manager import recording_schedule_manager
from app.services.recording_start import start_regular_recorder
from app.services.system_settings import load_runtime_settings

router = APIRouter(prefix="/api/cameras/onvif", tags=["onvif-cameras"])


def _resolved_form_factor(manufacturer: str | None, model: str | None, requested: str) -> str:
    if requested != "unknown":
        return requested
    guess = infer_camera_form_factor(manufacturer, model)
    if guess is not None and guess.confidence == "high":
        return guess.form_factor
    return requested


def _rtsp_legacy_fields(uri: str, fallback_host: str) -> tuple[str, int, str]:
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "rtsp":
        raise HTTPException(status_code=502, detail="ONVIF 返回的主码流不是 RTSP")
    host = parsed.hostname or fallback_host
    port = parsed.port or 554
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return host, port, path


def _profile(result: OnvifProbeResult, token: str):
    return next((item for item in result.profiles if item.token == token), None)


def _codec_name(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"h265", "hevc"}:
        return "hevc"
    if normalized in {"h264", "avc"}:
        return "h264"
    return normalized


def _fps_ratio(value: float | None) -> tuple[int | None, int | None]:
    if value is None or value <= 0:
        return None, None
    ratio = Fraction(str(value)).limit_denominator(1001)
    return ratio.numerator, ratio.denominator


async def _probe_onvif(payload: OnvifProbeRequest) -> OnvifProbeResult:
    client = OnvifClient(
        device_service_url=payload.device_service_url,
        username=payload.username,
        password=payload.password,
    )
    try:
        value = await client.probe()
    except OnvifError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return OnvifProbeResult.model_validate(value)


async def _validated_discovery(
    payload: OnvifProbeRequest,
    db: AsyncSession,
) -> tuple[
    OnvifProbeResult,
    dict,
    object | None,
    str,
    int,
    str,
    str | None,
]:
    discovered = await _probe_onvif(payload)
    main_profile = _profile(discovered, discovered.recording_profile_token)
    host, rtsp_port, rtsp_path = _rtsp_legacy_fields(discovered.recording_uri, payload.host)
    sub_rtsp_path = None
    if discovered.preview_profile_token != discovered.recording_profile_token:
        _sub_host, _sub_port, sub_rtsp_path = _rtsp_legacy_fields(
            discovered.preview_uri,
            payload.host,
        )

    runtime = await load_runtime_settings(db)
    try:
        media = await probe_stream_uri(
            stream_uri=inject_uri_credentials(
                discovered.recording_uri,
                payload.username,
                payload.password,
            ),
            rtsp_timeout_us=runtime.rtsp_timeout_us,
        )
    except CameraProbeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"ONVIF 设备可访问，但主码流验证失败: {exc}",
        ) from exc
    return discovered, media, main_profile, host, rtsp_port, rtsp_path, sub_rtsp_path


def _apply_media_fields(camera: Camera, media: dict, main_profile) -> None:
    fps_num, fps_den = _fps_ratio(main_profile.fps if main_profile else None)
    camera.video_codec = media.get("video_codec") or _codec_name(
        main_profile.encoding if main_profile else None
    )
    camera.video_profile = media.get("video_profile")
    camera.width = media.get("width") or (main_profile.width if main_profile else None)
    camera.height = media.get("height") or (main_profile.height if main_profile else None)
    camera.fps_num = media.get("fps_num") or fps_num
    camera.fps_den = media.get("fps_den") or fps_den
    camera.pixel_format = media.get("pixel_format")
    camera.has_b_frames = media.get("has_b_frames")
    camera.video_time_base = media.get("video_time_base")
    camera.audio_codec = media.get("audio_codec")
    camera.audio_profile = media.get("audio_profile")
    camera.sample_rate = media.get("sample_rate")
    camera.channels = media.get("channels")
    camera.audio_frame_samples = media.get("audio_frame_samples")


def _apply_onvif_metadata(camera: Camera, discovered: OnvifProbeResult) -> None:
    metadata = camera.onvif_metadata
    if metadata is None:
        metadata = OnvifDeviceMetadata()
        camera.onvif_metadata = metadata
    metadata.device_service_url = discovered.device_service_url
    metadata.device_uuid = discovered.device_uuid
    metadata.capabilities_json = discovered.capabilities
    metadata.profiles_json = [item.model_dump() for item in discovered.profiles]
    metadata.recording_profile_token = discovered.recording_profile_token
    metadata.preview_profile_token = discovered.preview_profile_token
    metadata.detection_profile_token = discovered.detection_profile_token
    metadata.recording_uri = discovered.recording_uri
    metadata.preview_uri = discovered.preview_uri
    metadata.detection_uri = discovered.detection_uri


@router.post("/probe", response_model=OnvifProbeResult)
async def probe_onvif_camera(payload: OnvifProbeRequest):
    return await _probe_onvif(payload)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
async def create_onvif_camera(
    payload: OnvifCameraCreate,
    db: AsyncSession = Depends(get_db),
):
    (
        discovered,
        media,
        main_profile,
        host,
        rtsp_port,
        rtsp_path,
        sub_rtsp_path,
    ) = await _validated_discovery(payload, db)

    camera = Camera(
        name=payload.name,
        manufacturer=discovered.manufacturer,
        model=discovered.model,
        form_factor=_resolved_form_factor(
            discovered.manufacturer,
            discovered.model,
            payload.form_factor,
        ),
        connection_type="onvif",
        ip=host,
        rtsp_port=rtsp_port,
        username=payload.username,
        password_encrypted=encrypt_secret(payload.password),
        rtsp_path=rtsp_path,
        sub_rtsp_path=sub_rtsp_path,
        enabled=payload.enabled,
        auto_record=payload.auto_record,
        recording_schedule_enabled=False,
        recording_schedule=[],
        timestamp_mode=payload.timestamp_mode,
        status="online",
    )
    _apply_media_fields(camera, media, main_profile)
    now = datetime.now(timezone.utc)
    camera.last_probe_at = now
    camera.last_online_at = now
    _apply_onvif_metadata(camera, discovered)
    db.add(camera)
    try:
        await db.flush()
        add_event(
            db,
            level="info",
            category="camera",
            code="camera.onvif_created",
            message=f"ONVIF 摄像头 {camera.name} 已创建",
            camera_id=camera.id,
            metadata={
                "manufacturer": discovered.manufacturer,
                "model": discovered.model,
                "profile_count": len(discovered.profiles),
                "recording_profile": discovered.recording_profile_token,
                "preview_profile": discovered.preview_profile_token,
            },
        )
        add_audit_event(
            db,
            code="operations.onvif_camera_created",
            message=f"ONVIF 摄像头 {camera.name} 已创建",
            camera_id=camera.id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="camera name already exists") from exc

    await db.refresh(camera)
    recording_schedule_manager.reset_for_schedule_change(camera.id)
    await recording_schedule_manager.reconcile()
    return camera


@router.put("/{camera_id}", response_model=CameraRead)
async def update_onvif_camera(
    camera_id: int,
    payload: OnvifCameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    if camera.connection_type != "onvif":
        raise HTTPException(status_code=409, detail="camera is not an ONVIF device")

    was_recording = recorder_manager.is_running(camera.id)
    (
        discovered,
        media,
        main_profile,
        host,
        rtsp_port,
        rtsp_path,
        sub_rtsp_path,
    ) = await _validated_discovery(payload, db)

    schedule_changed = False
    if payload.name is not None:
        camera.name = payload.name
    camera.manufacturer = discovered.manufacturer
    camera.model = discovered.model
    requested_form_factor = payload.form_factor if payload.form_factor is not None else camera.form_factor
    camera.form_factor = _resolved_form_factor(
        discovered.manufacturer,
        discovered.model,
        requested_form_factor,
    )
    camera.ip = host
    camera.rtsp_port = rtsp_port
    camera.username = payload.username
    camera.password_encrypted = encrypt_secret(payload.password)
    camera.rtsp_path = rtsp_path
    camera.sub_rtsp_path = sub_rtsp_path
    if payload.enabled is not None:
        schedule_changed = schedule_changed or payload.enabled != camera.enabled
        camera.enabled = payload.enabled
    if payload.auto_record is not None:
        schedule_changed = schedule_changed or payload.auto_record != camera.auto_record
        camera.auto_record = payload.auto_record
    if payload.timestamp_mode is not None:
        camera.timestamp_mode = payload.timestamp_mode
    _apply_media_fields(camera, media, main_profile)
    _apply_onvif_metadata(camera, discovered)
    now = datetime.now(timezone.utc)
    camera.status = "online"
    camera.last_probe_at = now
    camera.last_online_at = now

    add_event(
        db,
        level="info",
        category="camera",
        code="camera.onvif_updated",
        message=f"ONVIF 摄像头 {camera.name} 已重新探测并更新",
        camera_id=camera.id,
        metadata={
            "manufacturer": discovered.manufacturer,
            "model": discovered.model,
            "profile_count": len(discovered.profiles),
            "recording_profile": discovered.recording_profile_token,
            "preview_profile": discovered.preview_profile_token,
        },
    )
    add_audit_event(
        db,
        code="operations.onvif_camera_updated",
        message=f"ONVIF 摄像头 {camera.name} 已重新探测并更新",
        camera_id=camera.id,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="camera name already exists") from exc

    await db.refresh(camera)
    if was_recording:
        await recorder_manager.stop(camera.id)
    await motion_detection_manager.restart_camera(camera.id)
    if schedule_changed:
        recording_schedule_manager.reset_for_schedule_change(camera.id)
        await recording_schedule_manager.reconcile()
    elif was_recording:
        await start_regular_recorder(runtime_config(camera))
    return camera
