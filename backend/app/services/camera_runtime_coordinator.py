from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.services.camera_adapter_registry import get_camera_adapter_capability
from app.services.camera_config import runtime_config
from app.services.camera_media_session_registry import camera_media_session_registry
from app.services.event_recording import event_recording_manager
from app.services.motion_manager import motion_detection_manager
from app.services.onvif_event_manager import onvif_event_manager
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule_manager import RecordingOwner, recording_schedule_manager
from app.services.recording_start import start_regular_recorder

RuntimeReloadResult = Literal["missing", "disabled", "adapter_unavailable", "running"]


@dataclass(frozen=True)
class RuntimeStopSnapshot:
    was_recording: bool
    recording_owner: RecordingOwner | None


class CameraRuntimeCoordinator:
    """Coordinate per-camera runtime ownership across existing worker managers."""

    async def stop_all(
        self,
        camera_id: int,
        *,
        forget_schedule: bool = False,
    ) -> RuntimeStopSnapshot:
        snapshot = RuntimeStopSnapshot(
            was_recording=recorder_manager.is_running(camera_id),
            recording_owner=recording_schedule_manager.recording_owner(camera_id),
        )

        await camera_media_session_registry.stop_camera(camera_id)

        # Stop the detector first so it cannot confirm another event while the
        # pre-roll worker is being torn down. A runtime reload intentionally
        # invalidates any event ownership tied to the old connection.
        await motion_detection_manager.stop_camera(camera_id)
        await onvif_event_manager.restart_camera(camera_id)
        event_recording_manager.end_event(camera_id)
        await event_recording_manager.stop_camera(camera_id)

        if snapshot.was_recording:
            await recorder_manager.stop(camera_id)

        if forget_schedule:
            recording_schedule_manager.forget(camera_id)
        else:
            recording_schedule_manager.detach_for_runtime_reload(camera_id)
        return snapshot

    async def restore(
        self,
        camera_id: int,
        snapshot: RuntimeStopSnapshot,
        *,
        schedule_changed: bool = False,
    ) -> RuntimeReloadResult:
        async with SessionLocal() as db:
            camera = await db.get(Camera, camera_id)

        if camera is None:
            return "missing"
        if not camera.enabled:
            recording_schedule_manager.forget(camera_id)
            return "disabled"

        connection = getattr(camera, "connection", None)
        adapter = getattr(connection, "adapter", None) or getattr(
            camera,
            "connection_type",
            "manual_rtsp",
        )
        capability = await get_camera_adapter_capability(str(adapter))
        if not capability.available:
            return "adapter_unavailable"

        if (
            snapshot.recording_owner == "manual"
            and snapshot.was_recording
            and not schedule_changed
        ):
            await start_regular_recorder(runtime_config(camera))
            recording_schedule_manager.note_manual_start(camera_id)
        else:
            if schedule_changed:
                recording_schedule_manager.reset_for_schedule_change(camera_id)
            await recording_schedule_manager.reconcile()

        # Restore the pre-roll owner before motion detection so a newly confirmed
        # event cannot race ahead of its ring buffer after a configuration reload.
        await event_recording_manager.reconcile_once()
        await motion_detection_manager.restart_camera(camera_id)
        await onvif_event_manager.restart_camera(camera_id)
        return "running"

    async def reload(
        self,
        camera_id: int,
        *,
        schedule_changed: bool = False,
    ) -> RuntimeReloadResult:
        snapshot = await self.stop_all(camera_id)
        return await self.restore(
            camera_id,
            snapshot,
            schedule_changed=schedule_changed,
        )


camera_runtime_coordinator = CameraRuntimeCoordinator()
