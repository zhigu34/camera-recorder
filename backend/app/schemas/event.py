from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
import json


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

    @property
    def metadata(self) -> dict[str, Any] | None:
        if not self.metadata_json:
            return None
        try:
            value = json.loads(self.metadata_json)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
