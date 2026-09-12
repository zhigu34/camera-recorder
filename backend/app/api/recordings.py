import os
from datetime import date as Date, datetime, time, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.recording import Recording
from app.models.upload import UploadTask
from app.schemas.recording import RecordingRead
from app.services.cloud_playback import cloud_playback_manager
from app.services.cloud_stream import openlist_cloud_streamer
from app.services.recording_playback import PlaybackProxyError, recording_playback_manager
from app.services.system_settings import load_runtime_settings
from app.services.upload_manager import WebDAVError

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
    tz = _deployment_timezone()
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    else:
        value = value.astimezone(tz)
    return value.isoformat(timespec="seconds")


def _resolved_source(recording: Recording) -> tuple[Path, str]:
    local = Path(recording.mp4_path)
    if local.exists():
        return local, "local"
    cloud = cloud_playback_manager.source_path(recording.id)
    if cloud.exists() and cloud.stat().st_size > 0:
        cloud_playback_manager.mark_accessed(recording.id)
        return cloud, "cloud_cache"
    return local, "missing"


def _internal_cloud_stream_url(recording_id: int) -> str:
    # The backend container always listens on 8000 internally. FFmpeg can consume
    # this URL without ever receiving OpenList credentials. The endpoint will
    # either proxy Range bytes or follow OpenList's provider redirect.
    return f"http://127.0.0.1:8000/api/recordings/{recording_id}/cloud-stream"


async def _successful_upload_task(
    recording_id: int, db: AsyncSession
) -> UploadTask | None:
    return await db.scalar(
        select(UploadTask).where(
            UploadTask.recording_id == recording_id,
            UploadTask.status == "success",
        )
    )


def _playback_payload(recording: Recording) -> dict:
    proxy_state = recording_playback_manager.status(recording.id, recording.video_codec)
    source, source_kind = _resolved_source(recording)
    cloud_state = cloud_playback_manager.status(recording.id)
    remote_available = recording.upload_status == "success"
    if source_kind == "missing" and remote_available:
        source_kind = "openlist_stream"
    return {
        **proxy_state,
        "video_codec": recording.video_codec,
        "audio_codec": recording.audio_codec,
        "original_available": source.exists(),
        "source_kind": source_kind,
        "remote_available": remote_available,
        "cloud_state": cloud_state["state"],
        "cloud_error": cloud_state.get("error"),
        "can_try_original": recording_playback_manager.can_try_original(recording.video_codec),
    }


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


@router.get("/calendar")
async def recording_calendar(
    camera_id: int,
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        month_start = datetime.strptime(f"{month}-01", "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid month") from exc
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    rows = list(
        await db.scalars(
            select(Recording)
            .where(
                Recording.camera_id == camera_id,
                Recording.started_at.is_not(None),
                Recording.started_at >= month_start,
                Recording.started_at < month_end,
            )
            .order_by(Recording.started_at.asc(), Recording.id.asc())
            .limit(10000)
        )
    )
    days: dict[str, dict] = {}
    for recording in rows:
        if recording.started_at is None:
            continue
        day = recording.started_at.date().isoformat()
        item = days.setdefault(
            day,
            {
                "date": day,
                "count": 0,
                "total_duration": 0.0,
                "total_size": 0,
                "remote_only": 0,
                "warning_count": 0,
            },
        )
        item["count"] += 1
        item["total_duration"] += float(recording.duration or 0)
        item["total_size"] += int(recording.file_size or 0)
        if recording.status == "deleted" and recording.upload_status == "success":
            item["remote_only"] += 1
        if recording.health_status != "healthy" or int(recording.warning_count or 0) > 0:
            item["warning_count"] += 1

    result = []
    for item in days.values():
        item["total_duration"] = round(item["total_duration"], 3)
        result.append(item)
    return {
        "camera_id": camera_id,
        "month": month,
        "timezone": str(_deployment_timezone()),
        "days": result,
    }


@router.get("/browser")
async def browse_recordings(
    camera_id: int,
    date: Date,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await recording_playback_manager.cleanup_cache()
    await cloud_playback_manager.cleanup_cache()
    tz = _deployment_timezone()
    local_start = datetime.combine(date, time.min)
    local_end = datetime.combine(date, time.max)

    recordings = list(
        await db.scalars(
            select(Recording)
            .where(
                Recording.camera_id == camera_id,
                Recording.started_at.is_not(None),
                Recording.started_at >= local_start,
                Recording.started_at <= local_end,
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
                "playback": _playback_payload(recording),
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
    return _playback_payload(recording)


@router.post("/{recording_id}/cloud-playback")
async def prepare_cloud_playback(recording_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Compatibility probe for the old pre-download cloud playback flow.

    V0.8.6 no longer downloads the whole MP4 before playback. Returning
    `original_available=True` tells older frontends that an original source is
    immediately consumable; `/stream?source=original` will route it through the
    OpenList direct/Range bridge.
    """

    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")

    source, _ = _resolved_source(recording)
    if source.exists():
        return _playback_payload(recording)
    if recording.upload_status != "success":
        raise HTTPException(status_code=409, detail="录像尚未成功归档，无法云端回放")
    task = await _successful_upload_task(recording.id, db)
    if task is None:
        raise HTTPException(status_code=409, detail="未找到成功归档记录")

    payload = _playback_payload(recording)
    payload.update(
        {
            "original_available": True,
            "source_kind": "openlist_stream",
            "cloud_state": "streaming",
            "cloud_error": None,
        }
    )
    return payload


@router.get("/{recording_id}/cloud-stream")
async def stream_cloud_recording(
    recording_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stream an archived MP4 from OpenList without exposing WebDAV credentials.

    OpenList 30x provider links are redirected to the browser when they point to a
    public external host. Otherwise this endpoint relays only the requested Range
    bytes. No complete original MP4 is written to local disk.
    """

    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")
    if recording.upload_status != "success":
        raise HTTPException(status_code=409, detail="录像尚未成功归档")
    task = await _successful_upload_task(recording.id, db)
    if task is None:
        raise HTTPException(status_code=409, detail="未找到成功归档记录")

    runtime = await load_runtime_settings(db)
    try:
        handle = await openlist_cloud_streamer.open(
            task.remote_path,
            runtime,
            range_header=request.headers.get("range"),
            if_range_header=request.headers.get("if-range"),
            follow_redirects=False,
        )
        direct = openlist_cloud_streamer.public_redirect(handle)
        if direct:
            await handle.close()
            return RedirectResponse(
                direct,
                status_code=302,
                headers={
                    "Cache-Control": "no-store",
                    "X-Cloud-Playback": "openlist-direct",
                },
            )

        # Relative/same-host redirects are often OpenList's own /d or /p paths.
        # Follow those inside Docker instead of leaking an unreachable hostname to
        # the browser.
        if handle.response.status_code in {301, 302, 303, 307, 308}:
            await handle.close()
            handle = await openlist_cloud_streamer.open(
                task.remote_path,
                runtime,
                range_header=request.headers.get("range"),
                if_range_header=request.headers.get("if-range"),
                follow_redirects=True,
            )

        return StreamingResponse(
            handle.iter_bytes(),
            status_code=handle.response.status_code,
            media_type=handle.response.headers.get("content-type", "video/mp4"),
            headers=handle.response_headers(),
        )
    except WebDAVError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{recording_id}/playback")
async def prepare_playback(recording_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")
    source, _ = _resolved_source(recording)
    media_source: Path | str = source
    if not source.exists():
        task = await _successful_upload_task(recording.id, db)
        if recording.upload_status == "success" and task is not None:
            media_source = _internal_cloud_stream_url(recording.id)
    try:
        return await recording_playback_manager.start(
            recording.id,
            media_source,
            recording.video_codec,
            recording.audio_codec,
            duration_seconds=recording.duration,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="playback source is not available")


@router.get("/{recording_id}/proxy-live.mp4")
async def stream_live_proxy(
    recording_id: int,
    start_seconds: float = Query(default=0.0, ge=0.0, le=86400.0),
    db: AsyncSession = Depends(get_db),
):
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")

    source, _ = _resolved_source(recording)
    media_source: Path | str = source
    if not source.exists():
        task = await _successful_upload_task(recording.id, db)
        if recording.upload_status == "success" and task is not None:
            media_source = _internal_cloud_stream_url(recording.id)
        else:
            raise HTTPException(status_code=410, detail="playback source is not available")

    duration = max(0.0, float(recording.duration or 0))
    if duration > 0:
        start_seconds = min(start_seconds, max(0.0, duration - 0.25))

    state = recording_playback_manager.status(recording.id, recording.video_codec)
    if state["state"] == "ready":
        proxy = recording_playback_manager.proxy_path(recording.id)
        recording_playback_manager.mark_accessed(recording.id)
        return FileResponse(proxy, media_type="video/mp4")

    try:
        session = await recording_playback_manager.open_live_proxy(
            recording.id,
            media_source,
            recording.audio_codec,
            duration_seconds=recording.duration,
            start_seconds=start_seconds,
        )
    except PlaybackProxyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="playback source is not available")

    if session is None:
        proxy = recording_playback_manager.proxy_path(recording.id)
        recording_playback_manager.mark_accessed(recording.id)
        return FileResponse(proxy, media_type="video/mp4")

    return StreamingResponse(
        session.stream(),
        media_type="video/mp4",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Playback-Mode": "live-proxy",
            "X-Playback-Start-Seconds": f"{start_seconds:.3f}",
        },
    )


@router.get("/{recording_id}/stream")
async def stream_recording(
    recording_id: int,
    source: Literal["auto", "original", "proxy"] = Query(default="auto"),
    db: AsyncSession = Depends(get_db),
):
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")

    if source == "proxy":
        state = recording_playback_manager.status(recording.id, recording.video_codec)
        if state["state"] != "ready":
            raise HTTPException(status_code=409, detail="playback proxy is not ready")
        path = recording_playback_manager.proxy_path(recording.id)
        recording_playback_manager.mark_accessed(recording.id)
        if not path.exists():
            raise HTTPException(status_code=410, detail="playback file no longer exists")
        return FileResponse(path, media_type="video/mp4")

    use_original = source == "original" or recording_playback_manager.can_direct_play(
        recording.video_codec
    )
    if use_original:
        path, kind = _resolved_source(recording)
        if path.exists():
            if kind == "cloud_cache":
                cloud_playback_manager.mark_accessed(recording.id)
            return FileResponse(path, media_type="video/mp4")
        task = await _successful_upload_task(recording.id, db)
        if recording.upload_status == "success" and task is not None:
            return RedirectResponse(
                url=f"/api/recordings/{recording.id}/cloud-stream",
                status_code=307,
                headers={"Cache-Control": "no-store"},
            )
        raise HTTPException(status_code=410, detail="playback file no longer exists")

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
