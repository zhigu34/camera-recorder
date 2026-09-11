from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.event import Event
from app.schemas.event import EventRead

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=list[EventRead])
async def list_events(
    camera_id: int | None = None,
    level: str | None = None,
    category: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    statement = select(Event).order_by(Event.created_at.desc(), Event.id.desc())
    if camera_id is not None:
        statement = statement.where(Event.camera_id == camera_id)
    if level:
        statement = statement.where(Event.level == level)
    if category:
        statement = statement.where(Event.category == category)
    result = await db.scalars(statement.limit(limit))
    return list(result)
