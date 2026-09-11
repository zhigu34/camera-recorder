import os
from datetime import date as Date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.recording import Recording
from app.schemas.recording import RecordingRead
from app.services.recording_playback import recording_playback_manager

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


def _deployment_timezone():
    name = os.getenv("TZ", "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _local_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_deployment_timezone()).isoformat(timespec="seconds")


@router.get("", response_model=list[RecordingRead])
async def list_recordings(
    camera_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    statement = select(Recording).order_by(Recording.started_at.desc(), Recording.id.desc())
    if camera_id is not None:
        statement = statement.where(Recording.camera_id == camera_id)
    result = await db.scalars(statement.limit(limit))
    return list(result)


@router.get("/browser")
async def browse_recordings(
    camera_id: int,
    date: Date,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await recording_playback_manager.cleanup_cache()
    tz = _deployment_timezone()
    local_start = datetime.combine(date, time.min, tzinfo=tz)
    local_end = datetime.combine(date, time.max, tzinfo=tz)
    utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    utc_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)

    recordings = list(
        await db.scalars(
            select(Recording)
            .where(
                Recording.camera_id == camera_id,
                Recording.started_at.is_not(None),
                Recording.started_at >= utc_start,
                Recording.started_at <= utc_end,
                Recording.status.in_(("ready", "deleted")),
            )
            .order_by(Recording.started_at.asc(), Recording.id.asc())
            .limit(2000)
        )
    )

    items = []
    total_duration = 0.0
    total_size = 0
    for recording in recordings:
        total_duration += float(recording.duration or 0)
        total_size += int(recording.file_size or 0)
        playback = recording_playback_manager.status(recording.id, recording.video_codec)
        items.append(
            {
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
                "playback": playback,
            }
        )

    return {
        "camera_id": camera_id,
        "date": date.isoformat(),
        "timezone": str(tz),
        "count": len(items),
        "total_duration": round(total_duration, 3),
        "total_size": total_size,
        "items": items,
    }


@router.get("/{recording_id}/playback")
async def playback_status(recording_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")
    return recording_playback_manager.status(recording.id, recording.video_codec)


@router.post("/{recording_id}/playback")
async def prepare_playback(recording_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")
    source = Path(recording.mp4_path)
    try:
        return await recording_playback_manager.start(recording.id, source, recording.video_codec)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="local recording file no longer exists")


@router.get("/{recording_id}/stream")
async def stream_recording(recording_id: int, db: AsyncSession = Depends(get_db)):
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")

    if recording_playback_manager.can_direct_play(recording.video_codec):
        path = Path(recording.mp4_path)
    else:
        state = recording_playback_manager.status(recording.id, recording.video_codec)
        if state["state"] != "ready":
            raise HTTPException(status_code=409, detail="playback proxy is not ready")
        path = recording_playback_manager.proxy_path(recording.id)
        recording_playback_manager.mark_accessed(recording.id)

    if not path.exists():
        raise HTTPException(status_code=410, detail="playback file no longer exists")
    return FileResponse(path, media_type="video/mp4")


@router.get("/{recording_id}", response_model=RecordingRead)
async def get_recording(recording_id: int, db: AsyncSession = Depends(get_db)):
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")
    return recording
