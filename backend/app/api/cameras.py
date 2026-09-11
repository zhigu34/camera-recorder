from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.models.camera import Camera
from app.schemas.camera import (
    CameraBatchCreate,
    CameraBatchResult,
    CameraCreate,
    CameraProbeResult,
    CameraRead,
    CameraUpdate,
)
from app.services.camera_config import runtime_config
from app.services.camera_probe import CameraProbeError, probe_camera
from app.services.event_log import add_event
from app.services.recorder_manager import recorder_manager
from app.services.system_settings import load_runtime_settings

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


async def _camera_or_404(camera_id: int, db: AsyncSession) -> Camera:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


def _new_camera(payload: CameraCreate) -> Camera:
    return Camera(
        name=payload.name,
        ip=payload.ip,
        rtsp_port=payload.rtsp_port,
        username=payload.username,
        password_encrypted=encrypt_secret(payload.password),
        rtsp_path=payload.rtsp_path,
        enabled=payload.enabled,
        auto_record=payload.auto_record,
        timestamp_mode=payload.timestamp_mode,
    )


def _camera_password(camera: Camera) -> str:
    try:
        return decrypt_secret(camera.password_encrypted)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail="摄像头密码无法解密，请编辑该摄像头并重新输入密码后保存",
        ) from exc


def _runtime_config_or_409(camera: Camera):
    try:
        return runtime_config(camera)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail="摄像头密码无法解密，请编辑该摄像头并重新输入密码后保存",
        ) from exc


@router.get("", response_model=list[CameraRead])
async def list_cameras(db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Camera).order_by(Camera.id))
    return list(result)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
async def create_camera(payload: CameraCreate, db: AsyncSession = Depends(get_db)):
    camera = _new_camera(payload)
    db.add(camera)
    try:
        await db.flush()
        add_event(
            db,
            level="info",
            category="camera",
            code="camera.created",
            message=f"摄像头 {camera.name} 已创建",
            camera_id=camera.id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="camera name already exists") from exc
    await db.refresh(camera)
    return camera


@router.post("/batch", response_model=CameraBatchResult, status_code=status.HTTP_201_CREATED)
async def create_cameras_batch(payload: CameraBatchCreate, db: AsyncSession = Depends(get_db)):
    names = [item.name for item in payload.cameras]
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        raise HTTPException(
            status_code=422,
            detail=f"批量数据中存在重复名称: {', '.join(duplicates)}",
        )

    existing_result = await db.scalars(select(Camera.name).where(Camera.name.in_(names)))
    existing_names = set(existing_result.all())
    if existing_names and not payload.skip_existing:
        ordered = [name for name in names if name in existing_names]
        raise HTTPException(
            status_code=409,
            detail=f"以下摄像头名称已存在: {', '.join(ordered)}",
        )

    created_ids: list[int] = []
    skipped_names = [name for name in names if name in existing_names]
    try:
        for item in payload.cameras:
            if item.name in existing_names:
                continue
            camera = _new_camera(item)
            db.add(camera)
            await db.flush()
            created_ids.append(camera.id)
            add_event(
                db,
                level="info",
                category="camera",
                code="camera.created",
                message=f"摄像头 {camera.name} 已批量创建",
                camera_id=camera.id,
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="批量添加时检测到名称冲突，请刷新摄像头列表后重试",
        ) from exc

    return CameraBatchResult(
        created=len(created_ids),
        skipped=len(skipped_names),
        created_ids=created_ids,
        skipped_names=skipped_names,
    )


@router.get("/{camera_id}", response_model=CameraRead)
async def get_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    return await _camera_or_404(camera_id, db)


@router.put("/{camera_id}", response_model=CameraRead)
async def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    camera = await _camera_or_404(camera_id, db)
    values = payload.model_dump(exclude_unset=True)
    password = values.pop("password", None)
    for key, value in values.items():
        if value is not None:
            setattr(camera, key, value)
    if password is not None:
        camera.password_encrypted = encrypt_secret(password)

    add_event(
        db,
        level="info",
        category="camera",
        code="camera.updated",
        message=f"摄像头 {camera.name} 配置已更新",
        camera_id=camera.id,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="camera name already exists") from exc
    await db.refresh(camera)
    return camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    camera = await _camera_or_404(camera_id, db)
    if recorder_manager.is_running(camera_id):
        await recorder_manager.stop(camera_id)
    await db.delete(camera)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{camera_id}/probe", response_model=CameraProbeResult)
async def probe(camera_id: int, db: AsyncSession = Depends(get_db)):
    camera = await _camera_or_404(camera_id, db)
    runtime = await load_runtime_settings(db)
    password = _camera_password(camera)
    try:
        result = await probe_camera(
            ip=camera.ip,
            port=camera.rtsp_port,
            username=camera.username,
            password=password,
            rtsp_path=camera.rtsp_path,
            rtsp_timeout_us=runtime.rtsp_timeout_us,
        )
    except CameraProbeError as exc:
        camera.status = "probe_failed"
        camera.last_probe_at = datetime.now(timezone.utc)
        add_event(
            db,
            level="error",
            category="camera",
            code="camera.probe_failed",
            message=f"摄像头 {camera.name} Probe 失败: {str(exc)[-500:]}",
            camera_id=camera.id,
        )
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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
        setattr(camera, key, result.get(key))

    now = datetime.now(timezone.utc)
    camera.status = "online"
    camera.last_probe_at = now
    camera.last_online_at = now
    add_event(
        db,
        level="info",
        category="camera",
        code="camera.probe_ok",
        message=f"摄像头 {camera.name} Probe 成功",
        camera_id=camera.id,
        metadata={
            "video_codec": result.get("video_codec"),
            "width": result.get("width"),
            "height": result.get("height"),
            "fps": result.get("fps"),
            "audio_codec": result.get("audio_codec"),
            "sample_rate": result.get("sample_rate"),
        },
    )
    await db.commit()
    return result


@router.post("/{camera_id}/start")
async def start_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    camera = await _camera_or_404(camera_id, db)
    if camera.timestamp_mode == "reconstruct" and (not camera.fps_num or not camera.fps_den):
        raise HTTPException(status_code=409, detail="run camera Probe before reconstruct recording")
    runtime = await recorder_manager.start(_runtime_config_or_409(camera))
    camera.status = "recording"
    add_event(
        db,
        level="info",
        category="recorder",
        code="recorder.started",
        message=f"摄像头 {camera.name} 开始录像",
        camera_id=camera.id,
    )
    await db.commit()
    return runtime


@router.post("/{camera_id}/stop")
async def stop_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    camera = await _camera_or_404(camera_id, db)
    runtime = await recorder_manager.stop(camera_id)
    camera.status = "stopped"
    add_event(
        db,
        level="info",
        category="recorder",
        code="recorder.stopped",
        message=f"摄像头 {camera.name} 已停止录像",
        camera_id=camera.id,
    )
    await db.commit()
    return runtime


@router.post("/{camera_id}/restart")
async def restart_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    camera = await _camera_or_404(camera_id, db)
    if camera.timestamp_mode == "reconstruct" and (not camera.fps_num or not camera.fps_den):
        raise HTTPException(status_code=409, detail="run camera Probe before reconstruct recording")
    runtime = await recorder_manager.restart(_runtime_config_or_409(camera))
    camera.status = "recording"
    add_event(
        db,
        level="warning",
        category="recorder",
        code="recorder.restarted",
        message=f"摄像头 {camera.name} 录像进程已重启",
        camera_id=camera.id,
    )
    await db.commit()
    return runtime


@router.get("/{camera_id}/runtime")
async def camera_runtime(camera_id: int, db: AsyncSession = Depends(get_db)):
    await _camera_or_404(camera_id, db)
    return recorder_manager.status(camera_id)
