from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.models.recording import Recording
from app.services.event_recording import event_recording_manager
from app.services.recorder_manager import recorder_manager


def begin_recording_event(camera_id: int, started_at: datetime) -> None:
    """Pin pre-roll without exposing recorder lifecycle to motion detection."""

    event_recording_manager.begin_event(camera_id, started_at)


def end_recording_event(camera_id: int) -> None:
    """Release the ring pin after the event has been finalized."""

    event_recording_manager.end_event(camera_id)


async def resolve_event_recording(
    camera_id: int,
    started_at: datetime,
    ended_at: datetime,
) -> int | None:
    """Resolve the recording source that owned the event when it began.

    If the event ring owned the camera at event start, materialize that full
    pre-roll clip first even when a regular recorder started during the event.
    Otherwise reuse an overlapping regular recording when available.
    """

    capture_required = event_recording_manager.event_capture_required(camera_id)
    if capture_required:
        recording_id = await event_recording_manager.capture(camera_id, started_at, ended_at)
        if recording_id is not None:
            return recording_id

    async with SessionLocal() as db:
        recording = await db.scalar(
            select(Recording)
            .where(
                Recording.camera_id == camera_id,
                Recording.started_at.is_not(None),
                Recording.started_at <= ended_at,
                or_(Recording.ended_at.is_(None), Recording.ended_at >= started_at),
            )
            .order_by(Recording.started_at.desc())
            .limit(1)
        )
        if recording is not None:
            return int(recording.id)

    # A running regular recorder owns the camera when the event ring did not own
    # this event at its start. Its current segment may not have reached the table yet.
    if recorder_manager.is_running(camera_id):
        return None
    if capture_required:
        return None
    return await event_recording_manager.capture(camera_id, started_at, ended_at)
