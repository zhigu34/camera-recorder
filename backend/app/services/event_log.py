import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event


def add_event(
    session: AsyncSession,
    *,
    level: str,
    category: str,
    code: str,
    message: str,
    camera_id: int | None = None,
    recording_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    event = Event(
        camera_id=camera_id,
        recording_id=recording_id,
        level=level,
        category=category,
        code=code,
        message=message,
        metadata_json=(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) if metadata else None),
    )
    session.add(event)
    return event
