from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UploadTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recording_id: int
    provider: str
    remote_path: str
    status: str
    retry_count: int
    last_error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    next_retry_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
