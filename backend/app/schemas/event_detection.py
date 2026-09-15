from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.camera import CameraRead
from app.schemas.motion import MotionZoneRead

EventSourceKind = Literal["local", "camera_native"]
EventSourceStatus = Literal["available", "unavailable", "unsupported", "error"]
DetectionEventType = Literal[
    "motion",
    "person",
    "vehicle",
    "intrusion",
    "tamper",
    "digital_input",
    "unknown",
]


class EventSourceDescriptor(BaseModel):
    id: str
    provider: str
    source_kind: EventSourceKind
    status: EventSourceStatus
    display_name: str
    capabilities: list[str] = Field(default_factory=list)
    configurable: bool
    runtime_state: str | None = None
    reason: str | None = None


class EventSourceRead(BaseModel):
    descriptor: EventSourceDescriptor
    config: dict[str, Any] = Field(default_factory=dict)
    zones: list[MotionZoneRead] = Field(default_factory=list)


class DetectionCapabilitySlot(BaseModel):
    event_type: DetectionEventType
    status: EventSourceStatus
    source_id: str | None = None
    reason: str | None = None


class EventDetectionOverview(BaseModel):
    camera: CameraRead
    sources: list[EventSourceDescriptor] = Field(default_factory=list)
    capability_slots: list[DetectionCapabilitySlot] = Field(default_factory=list)
    enabled_source_ids: list[str] = Field(default_factory=list)


class DetectionEventRead(BaseModel):
    id: int
    camera_id: int
    source_kind: EventSourceKind
    provider: str
    event_type: DetectionEventType
    started_at: datetime
    ended_at: datetime
    confidence: float | None = None
    zone_id: int | None = None
    zone_name: str | None = None
    recording_id: int | None = None
    snapshot_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
