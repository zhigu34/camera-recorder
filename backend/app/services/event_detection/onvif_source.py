from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.motion import MotionDetectionSettings
from app.models.onvif_events import OnvifEventSettings
from app.schemas.event_detection import EventSourceDescriptor, EventSourceRead
from app.services.event_detection.registry import EventSourceConflict, EventSourceUnavailable
from app.services.onvif_event_manager import onvif_event_manager


class OnvifEventSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class OnvifNativeEventSource:
    source_id = "camera.onvif"

    @staticmethod
    def _capability_state(camera: Camera) -> tuple[str, list[str], str | None]:
        connection = getattr(camera, "connection", None)
        if connection is None or connection.adapter != "onvif":
            return "unsupported", [], "当前连接不是 ONVIF"
        if connection.verification_status != "verified":
            return "unavailable", [], "ONVIF 连接尚未验证"
        config = connection.onvif_config
        if config is None:
            return "unavailable", [], "ONVIF 当前连接缺少配置"

        capabilities = config.capabilities_json or {}
        events_url = capabilities.get("events_xaddr")
        if not isinstance(events_url, str) or not events_url:
            return "unsupported", [], "设备未公布 ONVIF Events 服务"

        raw_types = capabilities.get("event_types")
        event_types = (
            [str(value) for value in raw_types if isinstance(value, str)]
            if isinstance(raw_types, list)
            else []
        )
        reason = None if event_types else "Events 服务可用；重新连接检测可读取已知 Topic 能力"
        return "available", event_types, reason

    async def descriptor(
        self,
        camera: Camera,
        db: AsyncSession | None,
    ) -> EventSourceDescriptor:
        status, capabilities, reason = self._capability_state(camera)
        runtime = onvif_event_manager.status(int(camera.id))
        runtime_state = str(runtime.get("state")) if status == "available" else None
        if status == "available" and runtime_state == "reconnecting" and runtime.get("last_error"):
            status = "error"
            reason = str(runtime["last_error"])
        return EventSourceDescriptor(
            id=self.source_id,
            provider="onvif",
            source_kind="camera_native",
            status=status,
            display_name="摄像头原生 ONVIF",
            capabilities=capabilities,
            configurable=True,
            runtime_state=runtime_state,
            reason=reason,
        )

    async def read(self, camera: Camera, db: AsyncSession) -> EventSourceRead:
        settings = await db.get(OnvifEventSettings, int(camera.id))
        return EventSourceRead(
            descriptor=await self.descriptor(camera, db),
            config={"enabled": bool(settings and settings.enabled)},
            zones=[],
        )

    async def update(
        self,
        camera: Camera,
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> EventSourceRead:
        update = OnvifEventSourceUpdate.model_validate(payload)
        descriptor = await self.descriptor(camera, db)
        if update.enabled and descriptor.status not in {"available", "error"}:
            raise EventSourceUnavailable(descriptor.reason or "camera.onvif is unavailable")

        if update.enabled:
            motion = await db.get(MotionDetectionSettings, int(camera.id))
            if motion is not None and motion.enabled:
                raise EventSourceConflict("disable local.motion before enabling camera.onvif")

        settings = await db.get(OnvifEventSettings, int(camera.id))
        if settings is None:
            settings = OnvifEventSettings(camera_id=int(camera.id), enabled=update.enabled)
            db.add(settings)
        else:
            settings.enabled = update.enabled

        await db.commit()
        await onvif_event_manager.restart_camera(int(camera.id))
        return await self.read(camera, db)
