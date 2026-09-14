from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

TimestampMode = Literal["native", "reconstruct", "wallclock"]
PreviewStream = Literal["auto", "main", "sub"]
CameraFormFactor = Literal["unknown", "bullet", "dome", "turret", "ptz", "doorbell", "indoor", "panoramic"]


class RecordingWindow(BaseModel):
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    start: str
    end: str

    @field_validator("days")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        normalized = sorted(set(value))
        if not normalized or any(day < 0 or day > 6 for day in normalized):
            raise ValueError("days must contain weekday numbers from 0 to 6")
        return normalized

    @field_validator("start", "end")
    @classmethod
    def validate_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("time must use HH:MM format")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ValueError("time must use HH:MM format") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("time must use HH:MM format")
        return f"{hour:02d}:{minute:02d}"

    @model_validator(mode="after")
    def validate_window(self):
        if self.start == self.end:
            raise ValueError("recording window start and end cannot be equal")
        return self


class CameraBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    manufacturer: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    form_factor: CameraFormFactor = "unknown"
    ip: str = Field(min_length=1, max_length=255)
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    username: str = Field(default="admin", max_length=128)
    rtsp_path: str = Field(default="/ch1/main", min_length=1, max_length=255)
    sub_rtsp_path: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool = True
    auto_record: bool = False
    recording_schedule_enabled: bool = False
    recording_schedule: list[RecordingWindow] = Field(default_factory=list, max_length=32)
    timestamp_mode: TimestampMode = "reconstruct"

    @field_validator("manufacturer", "model", mode="before")
    @classmethod
    def normalize_optional_identity(cls, value: Any):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class CameraCreate(CameraBase):
    password: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.recording_schedule_enabled and not self.recording_schedule:
            raise ValueError("recording schedule requires at least one time window")
        # A weekly recording schedule is an automatic-recording policy. Treating
        # schedule_enabled=true together with auto_record=false as valid creates a
        # contradictory state where configured windows can never start recording.
        if self.recording_schedule_enabled:
            self.auto_record = True
        return self


class CameraBatchCreate(BaseModel):
    cameras: list[CameraCreate] = Field(min_length=1, max_length=200)
    skip_existing: bool = True


class CameraBatchResult(BaseModel):
    created: int
    skipped: int
    created_ids: list[int] = Field(default_factory=list)
    skipped_names: list[str] = Field(default_factory=list)


class RecordingScheduleBatchApply(BaseModel):
    camera_ids: list[int] = Field(min_length=1, max_length=200)
    auto_record: bool = True
    recording_schedule_enabled: bool = True
    recording_schedule: list[RecordingWindow] = Field(default_factory=list, max_length=32)

    @field_validator("camera_ids")
    @classmethod
    def validate_camera_ids(cls, value: list[int]) -> list[int]:
        normalized = list(dict.fromkeys(value))
        if any(camera_id <= 0 for camera_id in normalized):
            raise ValueError("camera_ids must contain positive integers")
        return normalized

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.recording_schedule_enabled and not self.recording_schedule:
            raise ValueError("recording schedule requires at least one time window")
        if self.recording_schedule_enabled:
            self.auto_record = True
        elif not self.auto_record:
            self.recording_schedule_enabled = False
        return self


class RecordingScheduleBatchResult(BaseModel):
    updated: int
    camera_ids: list[int]


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    manufacturer: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    form_factor: CameraFormFactor | None = None
    ip: str | None = Field(default=None, min_length=1, max_length=255)
    rtsp_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    rtsp_path: str | None = Field(default=None, min_length=1, max_length=255)
    sub_rtsp_path: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    auto_record: bool | None = None
    recording_schedule_enabled: bool | None = None
    recording_schedule: list[RecordingWindow] | None = Field(default=None, max_length=32)
    timestamp_mode: TimestampMode | None = None

    @field_validator("manufacturer", "model", mode="before")
    @classmethod
    def normalize_optional_identity(cls, value: Any):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def normalize_schedule_policy(self):
        if self.recording_schedule_enabled is True:
            if self.recording_schedule == []:
                raise ValueError("recording schedule requires at least one time window")
            self.auto_record = True
        elif self.auto_record is False:
            self.recording_schedule_enabled = False
        return self


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

    # status remains as a compatibility alias for connectivity_status. New
    # clients should use the explicit fields below and never infer one state
    # dimension from another.
    status: str
    connectivity_status: str = "unknown"
    connectivity_failures: int = 0
    recorder_state: str = "STOPPED"
    schedule_state: str = "disabled"
    last_probe_at: datetime | None = None
    last_online_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("recording_schedule", mode="before")
    @classmethod
    def normalize_legacy_schedule(cls, value: Any):
        # Historical rows may contain NULL or malformed schedule JSON. Reading the
        # camera list must never become a 500 because one old row is incomplete.
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if not isinstance(item, dict):
                continue
            try:
                normalized.append(RecordingWindow.model_validate(item).model_dump())
            except ValidationError:
                continue
        return normalized

    @model_validator(mode="after")
    def normalize_legacy_status(self):
        self.status = self.connectivity_status
        return self


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
