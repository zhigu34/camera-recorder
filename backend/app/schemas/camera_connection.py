from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CameraAdapter = Literal["manual_rtsp", "onvif", "hik_sdk"]


class _ConnectionWriteBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    username: str = Field(default="admin", max_length=128)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        host = value.strip()
        if not host or "://" in host or "/" in host:
            raise ValueError("host must be a hostname or IP address")
        return host


class ManualRtspConnectionCreate(_ConnectionWriteBase):
    adapter: Literal["manual_rtsp"] = "manual_rtsp"
    password: str = Field(min_length=1, max_length=512)
    port: int = Field(default=554, ge=1, le=65535)
    main_path: str = Field(min_length=1, max_length=255)
    sub_path: str | None = Field(default=None, min_length=1, max_length=255)


class _OnvifConnectionBase(_ConnectionWriteBase):
    port: int = Field(default=80, ge=1, le=65535)
    device_service_url: str | None = Field(default=None, max_length=2048)

    @field_validator("device_service_url", mode="before")
    @classmethod
    def normalize_device_service_url(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_device_service_url(self):
        if self.device_service_url is None:
            return self
        parsed = urlparse(self.device_service_url)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("invalid ONVIF device service URL") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("invalid ONVIF device service URL")
        declared_host = self.host.strip("[]").lower()
        if parsed.hostname.strip("[]").lower() != declared_host:
            raise ValueError("ONVIF device service URL host must match connection host")
        return self


class OnvifConnectionCreate(_OnvifConnectionBase):
    adapter: Literal["onvif"] = "onvif"
    password: str = Field(min_length=1, max_length=512)


class HikConnectionCreate(_ConnectionWriteBase):
    adapter: Literal["hik_sdk"] = "hik_sdk"
    password: str = Field(min_length=1, max_length=512)
    sdk_port: int = Field(default=8000, ge=1, le=65535)
    channel: int = Field(default=1, ge=1)
    main_stream_type: int = Field(default=0, ge=0)
    sub_stream_type: int = Field(default=1, ge=0)


CameraConnectionCreate = Annotated[
    ManualRtspConnectionCreate | OnvifConnectionCreate | HikConnectionCreate,
    Field(discriminator="adapter"),
]


class ManualRtspConnectionUpdate(_ConnectionWriteBase):
    adapter: Literal["manual_rtsp"] = "manual_rtsp"
    password: str | None = Field(default=None, min_length=1, max_length=512)
    port: int = Field(default=554, ge=1, le=65535)
    main_path: str = Field(min_length=1, max_length=255)
    sub_path: str | None = Field(default=None, min_length=1, max_length=255)


class OnvifConnectionUpdate(_OnvifConnectionBase):
    adapter: Literal["onvif"] = "onvif"
    password: str | None = Field(default=None, min_length=1, max_length=512)


class HikConnectionUpdate(_ConnectionWriteBase):
    adapter: Literal["hik_sdk"] = "hik_sdk"
    password: str | None = Field(default=None, min_length=1, max_length=512)
    sdk_port: int = Field(default=8000, ge=1, le=65535)
    channel: int = Field(default=1, ge=1)
    main_stream_type: int = Field(default=0, ge=0)
    sub_stream_type: int = Field(default=1, ge=0)


CameraConnectionUpdate = Annotated[
    ManualRtspConnectionUpdate | OnvifConnectionUpdate | HikConnectionUpdate,
    Field(discriminator="adapter"),
]


class ManualRtspConnectionReadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    port: int
    main_path: str
    sub_path: str | None = None


class OnvifConnectionReadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    port: int
    device_service_url: str
    device_uuid: str | None = None
    firmware_version: str | None = None
    serial_number: str | None = None
    hardware_id: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    profiles: list[dict[str, Any]] = Field(default_factory=list)
    recording_profile_token: str | None = None
    preview_profile_token: str | None = None
    detection_profile_token: str | None = None


class HikConnectionReadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sdk_port: int
    channel: int
    main_stream_type: int
    sub_stream_type: int
    device_serial: str | None = None
    device_model: str | None = None
    device_name: str | None = None


CameraConnectionReadConfig = (
    ManualRtspConnectionReadConfig | OnvifConnectionReadConfig | HikConnectionReadConfig
)


def _onvif_port(device_service_url: str) -> int:
    parsed = urlparse(device_service_url)
    if parsed.port is not None:
        return parsed.port
    return 443 if parsed.scheme.lower() == "https" else 80


class CameraConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    adapter: CameraAdapter
    host: str
    username: str
    password_set: bool
    revision: int
    verification_status: str
    verified_at: datetime | None = None
    last_error: str | None = None
    config: CameraConnectionReadConfig

    @model_validator(mode="before")
    @classmethod
    def project_connection(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return value
        adapter = getattr(value, "adapter", None)
        if adapter not in {"manual_rtsp", "onvif", "hik_sdk"}:
            return value

        base = {
            "id": getattr(value, "id", None),
            "adapter": adapter,
            "host": getattr(value, "host", None),
            "username": getattr(value, "username", None),
            "password_set": bool(getattr(value, "password_encrypted", None)),
            "revision": getattr(value, "revision", None),
            "verification_status": getattr(value, "verification_status", None),
            "verified_at": getattr(value, "verified_at", None),
            "last_error": getattr(value, "last_error", None),
        }

        if adapter == "manual_rtsp":
            config = getattr(value, "rtsp_config", None)
            base["config"] = {
                "port": getattr(config, "port", None),
                "main_path": getattr(config, "main_path", None),
                "sub_path": getattr(config, "sub_path", None),
            }
        elif adapter == "onvif":
            config = getattr(value, "onvif_config", None)
            device_service_url = getattr(config, "device_service_url", "")
            base["config"] = {
                "port": _onvif_port(device_service_url),
                "device_service_url": device_service_url,
                "device_uuid": getattr(config, "device_uuid", None),
                "firmware_version": getattr(config, "firmware_version", None),
                "serial_number": getattr(config, "serial_number", None),
                "hardware_id": getattr(config, "hardware_id", None),
                "capabilities": getattr(config, "capabilities_json", {}) or {},
                "profiles": getattr(config, "profiles_json", []) or [],
                "recording_profile_token": getattr(config, "recording_profile_token", None),
                "preview_profile_token": getattr(config, "preview_profile_token", None),
                "detection_profile_token": getattr(config, "detection_profile_token", None),
            }
        else:
            config = getattr(value, "hik_config", None)
            base["config"] = {
                "sdk_port": getattr(config, "sdk_port", None),
                "channel": getattr(config, "channel", None),
                "main_stream_type": getattr(config, "main_stream_type", None),
                "sub_stream_type": getattr(config, "sub_stream_type", None),
                "device_serial": getattr(config, "device_serial", None),
                "device_model": getattr(config, "device_model", None),
                "device_name": getattr(config, "device_name", None),
            }
        return base
