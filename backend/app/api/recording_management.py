from datetime import date as Date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.camera import Camera
from app.models.recording import Recording
from app.schemas.recording import RecordingRead

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
