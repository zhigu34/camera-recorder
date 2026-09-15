from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.database import get_db
from app.models.camera import Camera
from app.models.motion import MotionEvent, MotionZone
from app.schemas.motion import (
    MotionDetectionRead,
    MotionDetectionUpdate,
    MotionEventRead,
    MotionZoneCreate,
    MotionZoneRead,
    MotionZoneUpdate,
)
from app.services.motion_manager import motion_detection_manager
from app.services.motion_settings import read_motion_detection, update_motion_detection_settings

router = APIRouter(tags=["motion-detection"])


async def _camera_or_404(camera_id: int, db: AsyncSession) -> Camera:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


@router.get(
    "/api/cameras/{camera_id}/motion-detection",
    response_model=MotionDetectionRead,
)
async def get_motion_detection(camera_id: int, db: AsyncSession = Depends(get_db)):
    await _camera_or_404(camera_id, db)
    return await read_motion_detection(camera_id, db)


@router.put(
    "/api/cameras/{camera_id}/motion-detection",
    response_model=MotionDetectionRead,
)
async def update_motion_detection(
    camera_id: int,
    payload: MotionDetectionUpdate,
    db: AsyncSession = Depends(get_db),
):
    await _camera_or_404(camera_id, db)
    return await update_motion_detection_settings(camera_id, payload, db)


@router.post(
    "/api/cameras/{camera_id}/motion-zones",
    response_model=MotionZoneRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_motion_zone(
    camera_id: int,
    payload: MotionZoneCreate,
    db: AsyncSession = Depends(get_db),
):
    await _camera_or_404(camera_id, db)
    zone = MotionZone(
        camera_id=camera_id,
        name=payload.name,
        enabled=payload.enabled,
        polygon_json=payload.polygon,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    await motion_detection_manager.restart_camera(camera_id)
    return zone


async def _zone_or_404(camera_id: int, zone_id: int, db: AsyncSession) -> MotionZone:
    zone = await db.scalar(
        select(MotionZone).where(MotionZone.id == zone_id, MotionZone.camera_id == camera_id)
    )
    if zone is None:
        raise HTTPException(status_code=404, detail="motion zone not found")
    return zone


@router.put(
    "/api/cameras/{camera_id}/motion-zones/{zone_id}",
    response_model=MotionZoneRead,
)
async def update_motion_zone(
    camera_id: int,
    zone_id: int,
    payload: MotionZoneUpdate,
    db: AsyncSession = Depends(get_db),
):
    await _camera_or_404(camera_id, db)
    zone = await _zone_or_404(camera_id, zone_id, db)
    changes = payload.model_dump(exclude_unset=True)
    if "polygon" in changes:
        zone.polygon_json = changes.pop("polygon")
    for field, value in changes.items():
        setattr(zone, field, value)
    await db.commit()
    await db.refresh(zone)
    await motion_detection_manager.restart_camera(camera_id)
    return zone


@router.delete(
    "/api/cameras/{camera_id}/motion-zones/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_motion_zone(
    camera_id: int,
    zone_id: int,
    db: AsyncSession = Depends(get_db),
):
    await _camera_or_404(camera_id, db)
    zone = await _zone_or_404(camera_id, zone_id, db)
    await db.delete(zone)
    await db.commit()
    await motion_detection_manager.restart_camera(camera_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/motion-events", response_model=list[MotionEventRead])
async def list_motion_events(
    start: datetime = Query(...),
    end: datetime = Query(...),
    camera_id: int | None = Query(default=None, gt=0),
    zone_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    if camera_id is not None:
        await _camera_or_404(camera_id, db)
    if start > end:
        raise HTTPException(status_code=422, detail="start must not be after end")

    statement = select(MotionEvent).where(
        MotionEvent.started_at <= end,
        MotionEvent.ended_at >= start,
    )
    if camera_id is not None:
        statement = statement.where(MotionEvent.camera_id == camera_id)
    if zone_id is not None:
        statement = statement.where(MotionEvent.zone_id == zone_id)
    statement = statement.order_by(MotionEvent.started_at, MotionEvent.id).limit(limit)
    result = await db.scalars(statement)
    return list(result)


@router.get("/api/motion-events/{event_id}/snapshot")
async def get_motion_event_snapshot(event_id: int, db: AsyncSession = Depends(get_db)):
    event = await db.get(MotionEvent, event_id)
    if event is None or not event.snapshot_path:
        raise HTTPException(status_code=404, detail="motion event snapshot not found")

    path = Path(event.snapshot_path)
    if not path.is_absolute():
        path = app_settings.data_dir / path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="motion event snapshot not found")
    return FileResponse(path, media_type="image/jpeg", filename=f"motion-event-{event_id}.jpg")
