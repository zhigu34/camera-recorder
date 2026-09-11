from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TimestampMode = Literal["native", "reconstruct", "wallclock"]
PreviewStream = Literal["auto", "main", "sub"]


class CameraBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ip: str = Field(min_length=1, max_length=255)
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    username: str = Field(default="admin", max_length=128)
    rtsp_path: str = Field(default="/ch1/main", min_length=1, max_length=255)
    sub_rtsp_path: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool = True
    auto_record: bool = False
    timestamp_mode: TimestampMode = "reconstruct"


class CameraCreate(CameraBase):
    password: str = Field(min_length=1, max_length=512)


class CameraBatchCreate(BaseModel):
    cameras: list[CameraCreate] = Field(min_length=1, max_length=200)
    skip_existing: bool = True


class CameraBatchResult(BaseModel):
    created: int
    skipped: int
    created_ids: list[int] = Field(default_factory=list)
    skipped_names: list[str] = Field(default_factory=list)


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    ip: str | None = Field(default=None, min_length=1, max_length=255)
    rtsp_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    rtsp_path: str | None = Field(default=None, min_length=1, max_length=255)
    sub_rtsp_path: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    auto_record: bool | None = None
    timestamp_mode: TimestampMode | None = None


class CameraRead(CameraBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    password_set: bool = True

    video_codec: str | None = None
    video_profile: str | None = None
    width: int | None = None
    height: int | None = None
    fps_num: int | None = None
    fps_den: int | None = None
    pixel_format: str | None = None
    has_b_frames: int | None = None
    video_time_base: str | None = None

    audio_codec: str | None = None
    audio_profile: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    audio_frame_samples: int | None = None

    status: str
    last_probe_at: datetime | None = None
    last_online_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CameraProbeResult(BaseModel):
    ok: bool = True
    video_codec: str | None = None
    video_profile: str | None = None
    width: int | None = None
    height: int | None = None
    fps_num: int | None = None
    fps_den: int | None = None
    fps: float | None = None
    pixel_format: str | None = None
    has_b_frames: int | None = None
    video_time_base: str | None = None

    audio_codec: str | None = None
    audio_profile: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    audio_frame_samples: int | None = None


class CameraRuntimeStatus(BaseModel):
    camera_id: int
    state: str
    pid: int | None = None
    restart_count: int = 0
    warning_count: int = 0
    timestamp_warning_count: int = 0
    network_warning_count: int = 0
    last_error: str | None = None
