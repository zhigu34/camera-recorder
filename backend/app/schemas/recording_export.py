from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ExportMode = Literal["fast", "exact"]
GapPolicy = Literal["merge", "split"]
PackageMode = Literal["individual", "zip"]
ExportStatus = Literal["pending", "processing", "ready", "failed", "expired"]
ArtifactKind = Literal["mp4", "zip", "manifest"]


class ExportRangeRequest(BaseModel):
    camera_id: int = Field(gt=0)
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("export datetimes must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "ExportRangeRequest":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        if self.end_at - self.start_at > timedelta(hours=24):
            raise ValueError("export range cannot exceed 24 hours")
        return self


class ExportCreateRequest(ExportRangeRequest):
    export_mode: ExportMode = "fast"
    gap_policy: GapPolicy = "merge"
    package_mode: PackageMode = "individual"

    @model_validator(mode="after")
    def validate_package_mode(self) -> "ExportCreateRequest":
        if self.gap_policy == "merge" and self.package_mode != "individual":
            raise ValueError("zip packaging is only available for split exports")
        return self


class ExportIntervalRead(BaseModel):
    start_at: datetime
    end_at: datetime
    duration: float = Field(ge=0)


class ExportGroupRead(ExportIntervalRead):
    recording_ids: list[int] = Field(default_factory=list)


class ExportRangeAnalysisRead(BaseModel):
    camera_id: int
    requested_start_at: datetime
    requested_end_at: datetime
    recording_count: int = Field(ge=0)
    unavailable_count: int = Field(default=0, ge=0)
    requested_duration: float = Field(ge=0)
    covered_duration: float = Field(ge=0)
    continuous_groups: list[ExportGroupRead] = Field(default_factory=list)
    gaps: list[ExportIntervalRead] = Field(default_factory=list)
    unavailable_intervals: list[ExportIntervalRead] = Field(default_factory=list)
    exportable: bool = False


class ExportArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    export_job_id: int
    kind: ArtifactKind
    segment_index: int | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    file_size: int = 0
    created_at: datetime


class ExportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    requested_start_at: datetime
    requested_end_at: datetime
    export_mode: ExportMode
    gap_policy: GapPolicy
    package_mode: PackageMode
    status: ExportStatus
    progress: float
    gap_count: int
    requested_duration: float
    covered_duration: float
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None
