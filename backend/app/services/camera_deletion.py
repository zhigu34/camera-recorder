from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.detection_event import DetectionEvent
from app.models.event import Event
from app.models.health_sample import CameraHealthSample
from app.models.motion import MotionEvent
from app.models.recording import Recording
from app.models.upload import UploadTask
from app.schemas.camera import CameraDeletionImpact


async def camera_deletion_impact(
    db: AsyncSession,
    camera_id: int,
) -> CameraDeletionImpact:
    recordings = int(
        await db.scalar(
            select(func.count(Recording.id)).where(Recording.camera_id == camera_id)
        )
        or 0
    )
    motion_events = int(
        await db.scalar(
            select(func.count(MotionEvent.id)).where(MotionEvent.camera_id == camera_id)
        )
        or 0
    )
    detection_events = int(
        await db.scalar(
            select(func.count(DetectionEvent.id)).where(DetectionEvent.camera_id == camera_id)
        )
        or 0
    )
    health_samples = int(
        await db.scalar(
            select(func.count(CameraHealthSample.id)).where(
                CameraHealthSample.camera_id == camera_id
            )
        )
        or 0
    )
    blocking_events = int(
        await db.scalar(
            select(func.count(Event.id)).where(
                Event.camera_id == camera_id,
                Event.blocks_camera_delete.is_(True),
            )
        )
        or 0
    )
    pending_uploads = int(
        await db.scalar(
            select(func.count(UploadTask.id))
            .join(Recording, Recording.id == UploadTask.recording_id)
            .where(
                Recording.camera_id == camera_id,
                UploadTask.status != "success",
            )
        )
        or 0
    )

    return CameraDeletionImpact(
        camera_id=camera_id,
        recordings=recordings,
        motion_events=motion_events,
        detection_events=detection_events,
        health_samples=health_samples,
        blocking_events=blocking_events,
        pending_uploads=pending_uploads,
        can_delete=not any(
            (
                recordings,
                motion_events,
                detection_events,
                health_samples,
                blocking_events,
                pending_uploads,
            )
        ),
    )
