from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MotionSensitivity = Literal["low", "medium", "high"]
MotionRuntimeState = Literal[
    "disabled",
    "starting",
    "warming_up",
    "running",
    "stabilizing",
    "reconnecting",
    "error",
    "stopped",
]


class MotionDetectionUpdate(BaseModel):
    enabled: bool = False
    sensitivity: MotionSensitivity = "medium"
    analysis_fps: int = Field(default=5, ge=1, le=10)
    analysis_width: int = Field(default=640, ge=320, le=1280)
    min_duration_ms: int = Field(default=800, ge=100, le=10_000)
    merge_gap_ms: int = Field(default=10_000, ge=0, le=30_000)
    event_min_interval_ms: int = Field(default=60_000, ge=0, le=600_000)


class MotionZoneBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    polygon: list[list[float]]

    @field_validator("polygon")
    @classmethod
    def validate_polygon(cls, value: list[list[float]]) -> list[list[float]]:
        if len(value) < 3:
            raise ValueError("polygon requires at least three points")
        for point in value:
            if len(point) != 2:
                raise ValueError("polygon points must contain x and y")
            x, y = point
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("polygon coordinates must be normalized to 0..1")
        return value


class MotionZoneCreate(MotionZoneBase):
    pass


class MotionZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    polygon: list[list[float]] | None = None

    @field_validator("polygon")
    @classmethod
    def validate_polygon(cls, value: list[list[float]] | None) -> list[list[float]] | None:
        if value is None:
            return None
        return MotionZoneBase(name="zone", polygon=value).polygon


class MotionZoneRead(MotionZoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    created_at: datetime
    updated_at: datetime


class MotionRuntimeRead(BaseModel):
    state: MotionRuntimeState = "disabled"
    stream: Literal["main", "sub"] | None = None
    last_frame_at: datetime | None = None
    last_error: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    raw_score: float | None = Field(default=None, ge=0.0, le=1.0)
    moving_area_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    global_change_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    primary_zone_id: int | None = None
    global_change: bool = False


class MotionDetectionRead(MotionDetectionUpdate):
    runtime: MotionRuntimeRead = Field(default_factory=MotionRuntimeRead)
    zones: list[MotionZoneRead] = Field(default_factory=list)


class MotionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    zone_id: int | None = None
    recording_id: int | None = None
    started_at: datetime
    ended_at: datetime
    peak_score: float | None = None
    snapshot_path: str | None = None
    metadata_json: str | None = None
    created_at: datetime
