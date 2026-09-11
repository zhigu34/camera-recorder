from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.models.camera import Camera
from app.schemas.camera import CameraCreate, CameraProbeResult, CameraRead, CameraUpdate
from app.services.camera_config import runtime_config
from app.services.camera_probe import CameraProbeError, probe_camera
from app.services.recorder_manager import recorder_manager

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


async def _camera_or_404(camera_id: int, db: AsyncSession) -> Camera:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


@router.get("", response_model=list[CameraRead])
async def list_cameras(db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Camera).order_by(Camera.id))
    return list(result)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
async def create_camera(payload: CameraCreate, db: AsyncSession = Depends(get_db)):
    camera = Camera(
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
    db.add(camera)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="camera name already exists") from exc
    await db.refresh(camera)
    return camera


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
    try:
        result = await probe_camera(
            ip=camera.ip,
            port=camera.rtsp_port,
            username=camera.username,
            password=decrypt_secret(camera.password_encrypted),
            rtsp_path=camera.rtsp_path,
        )
    except CameraProbeError as exc:
        camera.status = "probe_failed"
        camera.last_probe_at = datetime.now(timezone.utc)
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
    await db.commit()
    return result


@router.post("/{camera_id}/start")
async def start_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    camera = await _camera_or_404(camera_id, db)
    if camera.timestamp_mode == "reconstruct" and (not camera.fps_num or not camera.fps_den):
        raise HTTPException(status_code=409, detail="run camera Probe before reconstruct recording")
    runtime = await recorder_manager.start(runtime_config(camera))
    camera.status = "recording"
    await db.commit()
    return runtime


@router.post("/{camera_id}/stop")
async def stop_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    camera = await _camera_or_404(camera_id, db)
    runtime = await recorder_manager.stop(camera_id)
    camera.status = "stopped"
    await db.commit()
    return runtime


@router.post("/{camera_id}/restart")
async def restart_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    camera = await _camera_or_404(camera_id, db)
    if camera.timestamp_mode == "reconstruct" and (not camera.fps_num or not camera.fps_den):
        raise HTTPException(status_code=409, detail="run camera Probe before reconstruct recording")
    runtime = await recorder_manager.restart(runtime_config(camera))
    camera.status = "recording"
    await db.commit()
    return runtime


@router.get("/{camera_id}/runtime")
async def camera_runtime(camera_id: int, db: AsyncSession = Depends(get_db)):
    await _camera_or_404(camera_id, db)
    return recorder_manager.status(camera_id)
