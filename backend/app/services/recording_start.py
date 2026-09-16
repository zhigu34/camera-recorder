from __future__ import annotations

from app.services.event_recording import event_recording_manager
from app.services.ffmpeg_builder import CameraRuntimeConfig
from app.services.recorder_manager import recorder_manager


async def start_regular_recorder(camera: CameraRuntimeConfig) -> dict:
    """Transfer camera ownership to the regular recorder without truncating events.

    Normally the event ring is stopped before CameraWorker starts so the main stream
    is not held by both recording paths. If the ring already owns an active event,
    keep it alive through that event's end so its five-second pre-roll and tail can
    still be materialized; capture will stop the ring once the event closes.
    """

    if not event_recording_manager.event_capture_required(camera.id):
        await event_recording_manager.stop_camera(camera.id)
    return await recorder_manager.start(camera)
