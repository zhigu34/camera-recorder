from __future__ import annotations

from typing import Literal

from app.core.database import SessionLocal
from app.models.camera import Camera

RevisionState = Literal["current", "stale", "unknown"]


async def connection_revision_state(
    camera_id: int,
    expected_revision: int | None,
) -> RevisionState:
    """Compare a worker's captured connection revision with persisted current state."""

    if expected_revision is None:
        return "current"

    try:
        async with SessionLocal() as db:
            camera = await db.get(Camera, camera_id)
    except Exception:
        return "unknown"

    if camera is None or not camera.enabled or camera.connection is None:
        return "stale"
    if camera.connection.revision != expected_revision:
        return "stale"
    return "current"
