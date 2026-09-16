from contextlib import suppress
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import encrypt_secret
from app.models.camera import Camera
from app.models.hikvision import HikDeviceMetadata
from app.schemas.camera import CameraRead
from app.schemas.hikvision import HikCameraCreate, HikCameraUpdate, HikProbeRequest, HikProbeResult
from app.services.camera_config import runtime_config
from app.services.camera_probe import CameraProbeError, probe_stream_uri
from app.services.event_log import add_audit_event, add_event
from app.services.event_recording import event_recording_manager
from app.services.hik_bridge_client import HikBridgeClient, HikBridgeClientError
from app.services.hik_media_adapter import HikBridgeTarget
from app.services.motion_manager import motion_detection_manager
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule_manager import recording_schedule_manager
from app.services.recording_start import start_regular_recorder
from app.services.system_settings import load_runtime_settings

router = APIRouter(prefix="/api/cameras/hik", tags=["hik-cameras"])


def _bridge_http_status(exc: HikBridgeClientError) -> int:
    code = exc.status_code
    if code is not None and 400 <= code < 600:
        return code
    return 502


async def _probe_hik(payload: HikProbeRequest) -> HikProbeResult:
    client = HikBridgeClient()
    try:
        value = await client.probe(
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=payload.password,
        )
    except HikBridgeClientError as exc:
        raise HTTPException(status_code=_bridge_http_status(exc), detail=str(exc)) from exc
    value = dict(value)
    value["channel"] = payload.channel
    return HikProbeResult.model_validate(value)


async def _validate_main_stream(payload: HikProbeRequest, db: AsyncSession) -> dict:
    runtime = await load_runtime_settings(db)
    client = HikBridgeClient()
    target = HikBridgeTarget(
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        channel=payload.channel,
        stream_type=0,
    )
    stream_id: str | None = None
    try:
        stream_id = await client.create_stream(target)
        return await probe_stream_uri(
            stream_uri=client.media_url(stream_id),
            rtsp_timeout_us=runtime.rtsp_timeout_us,
        )
    except HikBridgeClientError as exc:
        raise HTTPException(status_code=_bridge_http_status(exc), detail=str(exc)) from exc
    except CameraProbeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"HIK SDK 登录成功，但主码流验证失败: {exc}",
        ) from exc
    finally:
        if stream_id:
            with suppress(Exception):
                await client.stop_stream(stream_id)


def _apply_media_fields(camera: Camera, media: dict) -> None:
    camera.video_codec = media.get("video_codec")
    camera.video_profile = media.get("video_profile")
    camera.width = media.get("width")
    camera.height = media.get("height")
    camera.fps_num = media.get("fps_num")
    camera.fps_den = media.get("fps_den")
    camera.pixel_format = media.get("pixel_format")
    camera.has_b_frames = media.get("has_b_frames")
    camera.video_time_base = media.get("video_time_base")
    camera.audio_codec = media.get("audio_codec")
    camera.audio_profile = media.get("audio_profile")
    camera.sample_rate = media.get("sample_rate")
    camera.channels = media.get("channels")
    camera.audio_frame_samples = media.get("audio_frame_samples")


def _apply_hik_metadata(camera: Camera, payload: HikProbeRequest, discovered: HikProbeResult) -> None:
    metadata = camera.hik_metadata
    if metadata is None:
        metadata = HikDeviceMetadata()
        camera.hik_metadata = metadata
    metadata.sdk_port = payload.port
    metadata.channel = payload.channel
    metadata.main_stream_type = 0
    metadata.sub_stream_type = 1
    metadata.device_serial = discovered.serial_number
    metadata.device_model = discovered.device_model
    metadata.device_name = discovered.device_name


@router.post("/probe", response_model=HikProbeResult)
async def probe_hik_camera(payload: HikProbeRequest):
    return await _probe_hik(payload)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
async def create_hik_camera(
    payload: HikCameraCreate,
    db: AsyncSession = Depends(get_db),
):
    discovered = await _probe_hik(payload)
    media = await _validate_main_stream(payload, db)
    model = discovered.device_model or (
        f"HIK device type {discovered.device_type}" if discovered.device_type is not None else None
    )
    camera = Camera(
        name=payload.name,
        manufacturer="Hikvision",
        model=model,
        form_factor=payload.form_factor,
        connection_type="hik_sdk",
        ip=payload.host,
        rtsp_port=554,
        username=payload.username,
        password_encrypted=encrypt_secret(payload.password),
        rtsp_path="/hik-sdk/main",
        sub_rtsp_path="/hik-sdk/sub",
        enabled=payload.enabled,
        auto_record=payload.auto_record,
        recording_schedule_enabled=False,
        recording_schedule=[],
        timestamp_mode=payload.timestamp_mode,
        status="online",
    )
    _apply_media_fields(camera, media)
    _apply_hik_metadata(camera, payload, discovered)
    now = datetime.now(timezone.utc)
    camera.last_probe_at = now
    camera.last_online_at = now
    db.add(camera)
    try:
        await db.flush()
        add_event(
            db,
            level="info",
            category="camera",
            code="camera.hik_created",
            message=f"HIK SDK 摄像头 {camera.name} 已创建",
            camera_id=camera.id,
            metadata={
                "serial_number": discovered.serial_number,
                "device_type": discovered.device_type,
                "channel": payload.channel,
            },
        )
        add_audit_event(
            db,
            code="operations.hik_camera_created",
            message=f"HIK SDK 摄像头 {camera.name} 已创建",
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
async def update_hik_camera(
    camera_id: int,
    payload: HikCameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    if camera.connection_type != "hik_sdk":
        raise HTTPException(status_code=409, detail="camera is not a HIK SDK device")

    was_recording = recorder_manager.is_running(camera.id)
    discovered = await _probe_hik(payload)
    media = await _validate_main_stream(payload, db)
    schedule_changed = False

    if payload.name is not None:
        camera.name = payload.name
    camera.manufacturer = "Hikvision"
    camera.model = discovered.device_model or (
        f"HIK device type {discovered.device_type}" if discovered.device_type is not None else camera.model
    )
    if payload.form_factor is not None:
        camera.form_factor = payload.form_factor
    camera.ip = payload.host
    camera.username = payload.username
    camera.password_encrypted = encrypt_secret(payload.password)
    if payload.enabled is not None:
        schedule_changed = schedule_changed or payload.enabled != camera.enabled
        camera.enabled = payload.enabled
    if payload.auto_record is not None:
        schedule_changed = schedule_changed or payload.auto_record != camera.auto_record
        camera.auto_record = payload.auto_record
    if payload.timestamp_mode is not None:
        camera.timestamp_mode = payload.timestamp_mode
    _apply_media_fields(camera, media)
    _apply_hik_metadata(camera, payload, discovered)
    now = datetime.now(timezone.utc)
    camera.status = "online"
    camera.last_probe_at = now
    camera.last_online_at = now

    add_event(
        db,
        level="info",
        category="camera",
        code="camera.hik_updated",
        message=f"HIK SDK 摄像头 {camera.name} 已重新探测并更新",
        camera_id=camera.id,
        metadata={
            "serial_number": discovered.serial_number,
            "device_type": discovered.device_type,
            "channel": payload.channel,
        },
    )
    add_audit_event(
        db,
        code="operations.hik_camera_updated",
        message=f"HIK SDK 摄像头 {camera.name} 已重新探测并更新",
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
    # HIK worker URIs are stable backend-proxy URLs; force the event ring to
    # disconnect so a credential/channel change cannot keep the old SDK session.
    await event_recording_manager.stop_camera(camera.id)
    await motion_detection_manager.restart_camera(camera.id)
    if schedule_changed:
        recording_schedule_manager.reset_for_schedule_change(camera.id)
        await recording_schedule_manager.reconcile()
    elif was_recording:
        await start_regular_recorder(runtime_config(camera))
    return camera
