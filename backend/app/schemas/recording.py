from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RecordingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration: float | None = None
    mp4_path: str
    file_size: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    status: str
    health_status: str
    warning_count: int
    timestamp_warning_count: int
    network_warning_count: int
    upload_status: str
    created_at: datetime
