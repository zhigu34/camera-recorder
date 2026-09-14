import asyncio

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal, get_db
from app.models.event import Event
from app.models.motion import MotionEvent
from app.schemas.event import EventRead
from app.schemas.motion import MotionEventRead

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


def _cursor_value(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


@router.websocket("/ws/events")
async def events_websocket(websocket: WebSocket) -> None:
    """Stream newly persisted system and motion events from independent cursors.

    Clients that already loaded data through REST should pass ``after_id`` for
    system events and ``after_motion_id`` for motion activities. Missing cursors
    start at the current database tail so a new connection does not replay
    historical rows.
    """

    last_id = _cursor_value(websocket.query_params.get("after_id"))
    last_motion_id = _cursor_value(websocket.query_params.get("after_motion_id"))
    if last_id is None or last_motion_id is None:
        async with SessionLocal() as session:
            if last_id is None:
                last_id = int((await session.scalar(select(func.max(Event.id)))) or 0)
            if last_motion_id is None:
                last_motion_id = int((await session.scalar(select(func.max(MotionEvent.id)))) or 0)

    await websocket.accept()

    try:
        while True:
            async with SessionLocal() as session:
                event_rows = list(
                    await session.scalars(
                        select(Event)
                        .where(Event.id > last_id)
                        .order_by(Event.id.asc())
                        .limit(100)
                    )
                )
                motion_rows = list(
                    await session.scalars(
                        select(MotionEvent)
                        .where(MotionEvent.id > last_motion_id)
                        .order_by(MotionEvent.id.asc())
                        .limit(100)
                    )
                )

            for event in event_rows:
                payload = EventRead.model_validate(event).model_dump(mode="json")
                await websocket.send_json({"type": "event.created", "data": payload})
                last_id = event.id

            for event in motion_rows:
                payload = MotionEventRead.model_validate(event).model_dump(mode="json")
                await websocket.send_json({"type": "motion.created", "data": payload})
                last_motion_id = event.id

            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
            except TimeoutError:
                continue
            if message.get("type") == "websocket.disconnect":
                return
    except (WebSocketDisconnect, RuntimeError):
        return
