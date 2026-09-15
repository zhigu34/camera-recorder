import asyncio
from datetime import date as Date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.camera import Camera
from app.models.recording import Recording
from app.models.upload import UploadTask
from app.schemas.recording import RecordingRead
from app.services.event_log import add_event
from app.services.recording_playback import recording_playback_manager

router = APIRouter(prefix="/api/recording-management", tags=["recording-management"])


class RecordingManagementStats(BaseModel):
    total: int
    total_size: int
    archived: int
    pending_archive: int
    abnormal: int


class RecordingManagementPage(BaseModel):
    items: list[RecordingRead]
    total: int
    offset: int
    limit: int
    stats: RecordingManagementStats


class RecordingBatchDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class RecordingDeleteFailure(BaseModel):
    id: int
    error: str


class RecordingDeleteResult(BaseModel):
    requested: int
    deleted_local: int
    archived_remote_only: int
    removed_records: int
    skipped_uploading: list[int]
    already_remote_only: list[int]
    not_found: list[int]
    failed: list[RecordingDeleteFailure]


def _filters(
    camera_id: int | None,
    upload_status: str | None,
    health: Literal["healthy", "abnormal"] | None,
    storage: Literal["local", "cloud"] | None,
    date_from: Date | None,
    date_to: Date | None,
):
    filters = []
    if camera_id is not None:
        filters.append(Recording.camera_id == camera_id)
    if upload_status:
        filters.append(Recording.upload_status == upload_status)
    if health == "healthy":
        filters.extend((Recording.health_status == "healthy", Recording.warning_count == 0))
    elif health == "abnormal":
        filters.append(or_(Recording.health_status != "healthy", Recording.warning_count > 0))
    if storage == "local":
        filters.append(Recording.status != "deleted")
    elif storage == "cloud":
        filters.extend((Recording.status == "deleted", Recording.upload_status == "success"))
    if date_from is not None:
        filters.append(Recording.started_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        filters.append(Recording.started_at < datetime.combine(date_to + timedelta(days=1), time.min))
    return filters


async def _unlink_if_exists(path: Path | None) -> bool:
    if path is None or not path.exists():
        return False
    await asyncio.to_thread(path.unlink)
    return True


async def _purge_playback_cache(recording_id: int) -> None:
    await recording_playback_manager.cancel(recording_id)
    for path in (
        recording_playback_manager.proxy_path(recording_id),
        recording_playback_manager.live_temp_path(recording_id),
    ):
        try:
            await _unlink_if_exists(path)
        except OSError:
            # Playback compatibility cache is best-effort cleanup and must not
            # block deletion of the authoritative recording asset.
            pass


async def _delete_recordings(ids: list[int], db: AsyncSession) -> RecordingDeleteResult:
    unique_ids = list(dict.fromkeys(int(value) for value in ids if int(value) > 0))
    result = RecordingDeleteResult(
        requested=len(unique_ids),
        deleted_local=0,
        archived_remote_only=0,
        removed_records=0,
        skipped_uploading=[],
        already_remote_only=[],
        not_found=[],
        failed=[],
    )

    for recording_id in unique_ids:
        recording = await db.get(Recording, recording_id)
        if recording is None:
            result.not_found.append(recording_id)
            continue
        if recording.upload_status == "uploading":
            result.skipped_uploading.append(recording_id)
            continue
        if recording.status == "deleted" and recording.upload_status == "success":
            result.already_remote_only.append(recording_id)
            continue

        try:
            await _purge_playback_cache(recording.id)

            local_path = Path(recording.mp4_path)
            source_path = Path(recording.source_mkv_path) if recording.source_mkv_path else None
            local_available_before = local_path.exists()
            cloud_available = recording.upload_status == "success"
            local_deleted = await _unlink_if_exists(local_path)
            if source_path is not None and source_path != local_path:
                await _unlink_if_exists(source_path)
            if local_deleted:
                result.deleted_local += 1

            # Preserve the interval and storage context before the Recording row is
            # mutated or removed. Reliability diagnostics can then explain a later
            # timeline gap without retaining credentials or media URLs.
            add_event(
                db,
                level="info",
                category="recording",
                code="recording.deleted",
                message="手动删除录像",
                camera_id=recording.camera_id,
                recording_id=recording.id,
                metadata={
                    "recording_id": recording.id,
                    "started_at": recording.started_at.isoformat() if recording.started_at else None,
                    "ended_at": recording.ended_at.isoformat() if recording.ended_at else None,
                    "local_available_before": local_available_before,
                    "cloud_available": cloud_available,
                    "reason": "manual",
                },
            )

            if cloud_available:
                # Preserve the successful archive record and remote playback path.
                # Manual deletion only removes the local asset; it never deletes
                # the OpenList/WebDAV copy.
                recording.status = "deleted"
                result.archived_remote_only += 1
            else:
                # There is no safe remote copy. Once the local asset is removed,
                # remove upload bookkeeping and the recording row so the UI does
                # not retain a dead, unplayable shell.
                await db.execute(delete(UploadTask).where(UploadTask.recording_id == recording.id))
                await db.delete(recording)
                result.removed_records += 1
        except OSError as exc:
            result.failed.append(RecordingDeleteFailure(id=recording_id, error=str(exc)))

    await db.commit()
    return result


@router.get("", response_model=RecordingManagementPage)
async def recording_management(
    q: str | None = Query(default=None, max_length=200),
    camera_id: int | None = None,
    upload_status: str | None = Query(default=None, max_length=32),
    health: Literal["healthy", "abnormal"] | None = None,
    storage: Literal["local", "cloud"] | None = None,
    date_from: Date | None = None,
    date_to: Date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> RecordingManagementPage:
    filters = _filters(camera_id, upload_status, health, storage, date_from, date_to)
    statement = select(Recording)
    count_statement = select(func.count(Recording.id))

    needle = (q or "").strip().lower()
    if needle:
        statement = statement.join(Camera, Camera.id == Recording.camera_id)
        count_statement = count_statement.join(Camera, Camera.id == Recording.camera_id)
        search_filter = or_(
            func.lower(Recording.mp4_path).contains(needle),
            func.lower(Camera.name).contains(needle),
            func.lower(Camera.ip).contains(needle),
        )
        filters.append(search_filter)

    if filters:
        statement = statement.where(*filters)
        count_statement = count_statement.where(*filters)

    statement = statement.order_by(Recording.started_at.desc(), Recording.id.desc()).offset(offset).limit(limit)
    items = list(await db.scalars(statement))
    total = int((await db.execute(count_statement)).scalar_one() or 0)

    stats_row = (
        await db.execute(
            select(
                func.count(Recording.id),
                func.coalesce(func.sum(Recording.file_size), 0),
                func.coalesce(func.sum(case((Recording.upload_status == "success", 1), else_=0)), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (Recording.upload_status.in_(("pending", "uploading", "retry_wait", "failed")), 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (or_(Recording.health_status != "healthy", Recording.warning_count > 0), 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
        )
    ).one()

    return RecordingManagementPage(
        items=[RecordingRead.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
        stats=RecordingManagementStats(
            total=int(stats_row[0] or 0),
            total_size=int(stats_row[1] or 0),
            archived=int(stats_row[2] or 0),
            pending_archive=int(stats_row[3] or 0),
            abnormal=int(stats_row[4] or 0),
        ),
    )


@router.delete("/{recording_id}", response_model=RecordingDeleteResult)
async def delete_recording(
    recording_id: int,
    db: AsyncSession = Depends(get_db),
) -> RecordingDeleteResult:
    result = await _delete_recordings([recording_id], db)
    if result.not_found:
        raise HTTPException(status_code=404, detail="recording not found")
    if result.skipped_uploading:
        raise HTTPException(status_code=409, detail="录像正在上传，请等待上传结束后再删除")
    if result.already_remote_only:
        raise HTTPException(status_code=409, detail="录像已无本地文件，云端归档未删除")
    if result.failed:
        raise HTTPException(status_code=500, detail=result.failed[0].error)
    return result


@router.post("/batch-delete", response_model=RecordingDeleteResult)
async def batch_delete_recordings(
    payload: RecordingBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
) -> RecordingDeleteResult:
    return await _delete_recordings(payload.ids, db)
