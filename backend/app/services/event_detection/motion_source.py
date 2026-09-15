from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.schemas.event_detection import EventSourceDescriptor, EventSourceRead
from app.schemas.motion import MotionDetectionUpdate
from app.services.motion_manager import motion_detection_manager
from app.services.motion_settings import read_motion_detection, update_motion_detection_settings


class LocalMotionEventSource:
    source_id = "local.motion"

    async def descriptor(
        self,
        camera: Camera,
        db: AsyncSession | None,
    ) -> EventSourceDescriptor:
        runtime = motion_detection_manager.status(int(camera.id))
        return EventSourceDescriptor(
            id=self.source_id,
            provider="motion",
            source_kind="local",
            status="available",
            display_name="本地移动侦测",
            capabilities=["motion"],
            configurable=True,
            runtime_state=str(runtime.get("state")) if runtime else None,
        )

    async def read(self, camera: Camera, db: AsyncSession) -> EventSourceRead:
        value = await read_motion_detection(int(camera.id), db)
        return EventSourceRead(
            descriptor=await self.descriptor(camera, db),
            config={
                "enabled": value.enabled,
                "sensitivity": value.sensitivity,
                "analysis_fps": value.analysis_fps,
                "analysis_width": value.analysis_width,
                "min_duration_ms": value.min_duration_ms,
                "merge_gap_ms": value.merge_gap_ms,
                "event_min_interval_ms": value.event_min_interval_ms,
            },
            zones=value.zones,
        )

    async def update(
        self,
        camera: Camera,
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> EventSourceRead:
        validated = MotionDetectionUpdate.model_validate(payload)
        await update_motion_detection_settings(int(camera.id), validated, db)
        return await self.read(camera, db)
