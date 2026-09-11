import asyncio

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal, get_db
from app.models.event import Event
from app.schemas.event import EventRead

router = APIRouter(tags=["events"])


@router.get("/api/events", response_model=list[EventRead])
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


@router.websocket("/ws/events")
async def events_websocket(websocket: WebSocket) -> None:
    """Stream newly persisted events without replaying the full event history.

    Clients that already loaded events through REST should pass their highest
    event id as ``after_id``. Clients without a cursor start from the current
    database tail and receive only events created after the connection opens.
    """

    await websocket.accept()
    raw_after_id = websocket.query_params.get("after_id")
    if raw_after_id is None:
        async with SessionLocal() as session:
            last_id = int((await session.scalar(select(func.max(Event.id)))) or 0)
    else:
        try:
            last_id = max(0, int(raw_after_id))
        except ValueError:
            last_id = 0

    try:
        while True:
            async with SessionLocal() as session:
                result = await session.scalars(
                    select(Event)
                    .where(Event.id > last_id)
                    .order_by(Event.id.asc())
                    .limit(100)
                )
                rows = list(result)

            for event in rows:
                payload = EventRead.model_validate(event).model_dump(mode="json")
                await websocket.send_json({"type": "event.created", "data": payload})
                last_id = event.id

            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
            except TimeoutError:
                continue
            if message.get("type") == "websocket.disconnect":
                return
    except (WebSocketDisconnect, RuntimeError):
        return
