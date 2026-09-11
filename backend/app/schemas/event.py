import json
import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_serializer


def _event_timezone():
    """Return the deployment timezone used for human-facing event timestamps.

    SQLite CURRENT_TIMESTAMP is UTC and SQLite returns it as a naive datetime.
    Keep UTC in storage, then attach UTC explicitly and convert only when the
    API serializes the value for the Web UI. Docker Compose passes TZ through
    from .env (Asia/Shanghai by default).
    """

    name = os.getenv("TZ", "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int | None = None
    recording_id: int | None = None
    level: str
    category: str
    code: str
    message: str
    metadata_json: str | None = None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        # SQLite's CURRENT_TIMESTAMP is UTC but comes back without tzinfo.
        # Treat old and new naive values as UTC, then render in configured TZ.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(_event_timezone()).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def metadata(self) -> dict[str, Any] | None:
        if not self.metadata_json:
            return None
        try:
            value = json.loads(self.metadata_json)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
