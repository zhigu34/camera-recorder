from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.camera import CameraFormFactor, TimestampMode


class HikProbeRequest(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=8000, ge=1, le=65535)
    username: str = Field(default="admin", max_length=128)
    password: str = Field(min_length=1, max_length=512)
    channel: int = Field(default=1, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        host = value.strip()
        if not host or "://" in host or "/" in host:
            raise ValueError("host must be a hostname or IP address")
        return host


class HikCameraCreate(HikProbeRequest):
    name: str = Field(min_length=1, max_length=128)
    form_factor: CameraFormFactor = "unknown"
    connection_type: Literal["hik_sdk"] = "hik_sdk"
    enabled: bool = True
    auto_record: bool = False
    timestamp_mode: TimestampMode = "reconstruct"


class HikCameraUpdate(HikProbeRequest):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    form_factor: CameraFormFactor | None = None
    enabled: bool | None = None
    auto_record: bool | None = None
    timestamp_mode: TimestampMode | None = None


class HikProbeResult(BaseModel):
    ok: bool = True
    serial_number: str | None = None
    device_type: int | None = None
    device_model: str | None = None
    device_name: str | None = None
    start_channel: int | None = None
    analog_channel_count: int | None = None
    digital_channel_count: int | None = None
    channel: int = 1
