from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import cameras as cameras_api
from app.core.database import get_db
from app.core.security import encrypt_secret
from app.schemas.camera import CameraRead, CameraUpdate
from app.services.camera_connection import switch_to_manual_rtsp_connection
from app.services.camera_probe import CameraProbeError, probe_camera

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


def _apply_media_fields(camera, media: dict) -> None:
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


@router.put("/{camera_id}", response_model=CameraRead)
async def update_or_switch_to_manual_rtsp(
    camera_id: int,
    payload: CameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    camera = await cameras_api._camera_or_404(camera_id, db)
    connection = camera.connection
    current_adapter = connection.adapter if connection is not None else camera.connection_type

    if current_adapter == "manual_rtsp":
        return await cameras_api.update_camera(camera_id, payload, db)
    if connection is None:
        raise HTTPException(status_code=409, detail="camera has no current connection to switch")

    required = {"ip", "rtsp_port", "username", "password", "rtsp_path"}
    missing = sorted(required - payload.model_fields_set)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"manual RTSP switch requires: {', '.join(missing)}",
        )

    assert payload.ip is not None
    assert payload.rtsp_port is not None
    assert payload.username is not None
    assert payload.password is not None
    assert payload.rtsp_path is not None

    runtime = await cameras_api.load_runtime_settings(db)
    probe = getattr(cameras_api, "probe_camera", probe_camera)
    try:
        media = await probe(
            ip=payload.ip,
            port=payload.rtsp_port,
            username=payload.username,
            password=payload.password,
            rtsp_path=payload.rtsp_path,
            rtsp_timeout_us=runtime.rtsp_timeout_us,
        )
    except CameraProbeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    coordinator = cameras_api.camera_runtime_coordinator
    snapshot = await coordinator.stop_all(camera.id)

    values = payload.model_dump(exclude_unset=True)
    password = values.pop("password")
    values.pop("connection_type", None)
    host = values.pop("ip")
    port = values.pop("rtsp_port")
    username = values.pop("username")
    main_path = values.pop("rtsp_path")
    sub_path = values.pop("sub_rtsp_path", None)

    nullable_identity = {
        key: values.pop(key)
        for key in ("manufacturer", "model")
        if key in values
    }
    schedule_changed = bool(
        {"enabled", "auto_record", "recording_schedule_enabled", "recording_schedule"}
        & set(values)
    )
    for key, value in values.items():
        if value is not None:
            setattr(camera, key, value)
    for key, value in nullable_identity.items():
        setattr(camera, key, value)

    if camera.form_factor == "unknown":
        camera.form_factor = cameras_api._resolved_form_factor(
            camera.manufacturer,
            camera.model,
            camera.form_factor,
        )
    if camera.recording_schedule_enabled and not camera.recording_schedule:
        raise HTTPException(status_code=422, detail="启用录制时段后至少需要配置一个时间段")

    now = datetime.now(timezone.utc)
    _apply_media_fields(camera, media)
    switch_to_manual_rtsp_connection(
        camera,
        host=host,
        port=port,
        username=username,
        password_encrypted=encrypt_secret(password),
        main_path=main_path,
        sub_path=sub_path,
        verification_status="verified",
        verified_at=now,
        last_error=None,
    )
    camera.status = "online"
    camera.last_probe_at = now
    camera.last_online_at = now

    cameras_api.add_event(
        db,
        level="info",
        category="camera",
        code="camera.updated",
        message=f"摄像头 {camera.name} 配置已更新",
        camera_id=camera.id,
    )
    cameras_api.add_audit_event(
        db,
        code="operations.camera_updated",
        message=f"摄像头 {camera.name} 已切换为 manual_rtsp",
        camera_id=camera.id,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="camera name already exists") from exc

    await db.refresh(camera)
    await coordinator.restore(
        camera.id,
        snapshot,
        schedule_changed=schedule_changed,
    )
    return camera
