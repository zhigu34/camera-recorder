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
    blocks_camera_delete: bool = False,
) -> Event:
    event = Event(
        camera_id=camera_id,
        recording_id=recording_id,
        level=level,
        category=category,
        code=code,
        message=message,
        metadata_json=(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) if metadata else None),
        blocks_camera_delete=blocks_camera_delete,
    )
    session.add(event)
    return event


def add_audit_event(
    session: AsyncSession,
    *,
    code: str,
    message: str,
    camera_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    """Persist a non-secret administrative audit record in the shared Event table."""

    return add_event(
        session,
        level="info",
        category="audit",
        code=code,
        message=message,
        camera_id=camera_id,
        metadata=metadata,
        blocks_camera_delete=False,
    )
