from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.motion import MotionDetectionSettings, MotionZone
from app.models.onvif_events import OnvifEventSettings
from app.schemas.motion import MotionDetectionRead, MotionDetectionUpdate, MotionRuntimeRead
from app.services.event_source_errors import EventSourceConflict
from app.services.motion_manager import motion_detection_manager


async def motion_zones(camera_id: int, db: AsyncSession) -> list[MotionZone]:
    result = await db.scalars(
        select(MotionZone).where(MotionZone.camera_id == camera_id).order_by(MotionZone.id)
    )
    return list(result)


def motion_runtime(
    camera_id: int,
    settings: MotionDetectionSettings | None,
) -> MotionRuntimeRead:
    if settings is None or not settings.enabled:
        return MotionRuntimeRead(state="disabled")
    return MotionRuntimeRead(**motion_detection_manager.status(camera_id))


async def read_motion_detection(camera_id: int, db: AsyncSession) -> MotionDetectionRead:
    settings = await db.get(MotionDetectionSettings, camera_id)
    zones = await motion_zones(camera_id, db)
    if settings is None:
        return MotionDetectionRead(runtime=motion_runtime(camera_id, None), zones=zones)
    return MotionDetectionRead(
        enabled=settings.enabled,
        sensitivity=settings.sensitivity,
        analysis_fps=settings.analysis_fps,
        analysis_width=settings.analysis_width,
        min_duration_ms=settings.min_duration_ms,
        merge_gap_ms=settings.merge_gap_ms,
        event_min_interval_ms=settings.event_min_interval_ms,
        runtime=motion_runtime(camera_id, settings),
        zones=zones,
    )


async def update_motion_detection_settings(
    camera_id: int,
    payload: MotionDetectionUpdate,
    db: AsyncSession,
) -> MotionDetectionRead:
    if payload.enabled:
        onvif = await db.get(OnvifEventSettings, camera_id)
        if onvif is not None and onvif.enabled:
            raise EventSourceConflict("disable camera.onvif before enabling local.motion")

    settings = await db.get(MotionDetectionSettings, camera_id)
    if settings is None:
        settings = MotionDetectionSettings(camera_id=camera_id)
        db.add(settings)

    for field, value in payload.model_dump().items():
        setattr(settings, field, value)
    await db.commit()
    await db.refresh(settings)
    await motion_detection_manager.restart_camera(camera_id)
    return await read_motion_detection(camera_id, db)
