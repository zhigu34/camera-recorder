from __future__ import annotations

from app.services.event_recording import event_recording_manager
from app.services.ffmpeg_builder import CameraRuntimeConfig
from app.services.recorder_manager import recorder_manager


async def start_regular_recorder(camera: CameraRuntimeConfig) -> dict:
    """Transfer camera ownership from event prebuffer to the regular recorder.

    The event ring is deliberately stopped before CameraWorker is started, so the
    main stream is never held by both recording paths during a manual or scheduled
    transition. EventRecordingManager will recreate its ring after regular recording
    stops if motion detection remains enabled.
    """

    await event_recording_manager.stop_camera(camera.id)
    return await recorder_manager.start(camera)
