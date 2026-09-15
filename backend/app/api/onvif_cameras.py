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
from app.schemas.camera import CameraRead, OnvifCameraCreate, OnvifProbeRequest, OnvifProbeResult
from app.services.camera_identity import infer_camera_form_factor
from app.services.camera_probe import CameraProbeError, probe_stream_uri
from app.services.event_log import add_audit_event, add_event
from app.services.onvif_client import OnvifClient, OnvifError, inject_uri_credentials
from app.services.recording_schedule_manager import recording_schedule_manager
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


@router.post("/probe", response_model=OnvifProbeResult)
async def probe_onvif_camera(payload: OnvifProbeRequest):
    return await _probe_onvif(payload)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
async def create_onvif_camera(
    payload: OnvifCameraCreate,
    db: AsyncSession = Depends(get_db),
):
    discovered = await _probe_onvif(payload)
    main_profile = _profile(discovered, discovered.recording_profile_token)
    sub_profile = _profile(discovered, discovered.preview_profile_token)
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

    fps_num, fps_den = _fps_ratio(main_profile.fps if main_profile else None)
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
        video_codec=media.get("video_codec") or _codec_name(main_profile.encoding if main_profile else None),
        video_profile=media.get("video_profile"),
        width=media.get("width") or (main_profile.width if main_profile else None),
        height=media.get("height") or (main_profile.height if main_profile else None),
        fps_num=media.get("fps_num") or fps_num,
        fps_den=media.get("fps_den") or fps_den,
        pixel_format=media.get("pixel_format"),
        has_b_frames=media.get("has_b_frames"),
        video_time_base=media.get("video_time_base"),
        audio_codec=media.get("audio_codec"),
        audio_profile=media.get("audio_profile"),
        sample_rate=media.get("sample_rate"),
        channels=media.get("channels"),
        audio_frame_samples=media.get("audio_frame_samples"),
        status="online",
    )
    now = datetime.now(timezone.utc)
    camera.last_probe_at = now
    camera.last_online_at = now
    camera.onvif_metadata = OnvifDeviceMetadata(
        device_service_url=discovered.device_service_url,
        device_uuid=discovered.device_uuid,
        capabilities_json=discovered.capabilities,
        profiles_json=[item.model_dump() for item in discovered.profiles],
        recording_profile_token=discovered.recording_profile_token,
        preview_profile_token=discovered.preview_profile_token,
        detection_profile_token=discovered.detection_profile_token,
        recording_uri=discovered.recording_uri,
        preview_uri=discovered.preview_uri,
        detection_uri=discovered.detection_uri,
    )
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
