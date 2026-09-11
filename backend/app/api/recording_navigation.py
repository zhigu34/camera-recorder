from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.recordings import _local_iso, _playback_payload, _resolved_source, _successful_upload_task
from app.core.database import get_db
from app.models.recording import Recording
from app.services.recording_playback import recording_playback_manager

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


def _browser_item(recording: Recording) -> dict:
    return {
        "id": recording.id,
        "camera_id": recording.camera_id,
        "started_at": _local_iso(recording.started_at),
        "ended_at": _local_iso(recording.ended_at),
        "duration": recording.duration,
        "file_size": recording.file_size,
        "video_codec": recording.video_codec,
        "audio_codec": recording.audio_codec,
        "width": recording.width,
        "height": recording.height,
        "fps": recording.fps,
        "status": recording.status,
        "health_status": recording.health_status,
        "upload_status": recording.upload_status,
        "warning_count": recording.warning_count,
        "filename": Path(recording.mp4_path).name,
        "playback": _playback_payload(recording),
    }


async def _is_playable(recording: Recording, db: AsyncSession) -> bool:
    source, _ = _resolved_source(recording)
    if source.exists():
        return True

    proxy_state = recording_playback_manager.status(recording.id, recording.video_codec)
    if proxy_state["state"] == "ready":
        return True

    if recording.upload_status != "success":
        return False
    return await _successful_upload_task(recording.id, db) is not None


@router.get("/{recording_id}/adjacent")
async def adjacent_recording(
    recording_id: int,
    direction: Literal["previous", "next"] = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the nearest playable recording for the same camera.

    Navigation is global across natural-day boundaries. Unavailable historical rows
    are skipped, so an empty day or a locally-deleted/unarchived segment does not
    stop continuous playback.
    """

    current = await db.get(Recording, recording_id)
    if current is None:
        raise HTTPException(status_code=404, detail="recording not found")
    if current.started_at is None:
        return {"direction": direction, "item": None, "date": None}

    if direction == "next":
        boundary = or_(
            Recording.started_at > current.started_at,
            and_(Recording.started_at == current.started_at, Recording.id > current.id),
        )
        ordering = (Recording.started_at.asc(), Recording.id.asc())
    else:
        boundary = or_(
            Recording.started_at < current.started_at,
            and_(Recording.started_at == current.started_at, Recording.id < current.id),
        )
        ordering = (Recording.started_at.desc(), Recording.id.desc())

    candidates = list(
        await db.scalars(
            select(Recording)
            .where(
                Recording.camera_id == current.camera_id,
                Recording.started_at.is_not(None),
                boundary,
            )
            .order_by(*ordering)
            .limit(2000)
        )
    )

    for candidate in candidates:
        if await _is_playable(candidate, db):
            item = _browser_item(candidate)
            return {
                "direction": direction,
                "date": candidate.started_at.date().isoformat() if candidate.started_at else None,
                "item": item,
            }

    return {"direction": direction, "item": None, "date": None}
