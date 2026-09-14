from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.camera import CameraBase
from app.schemas.notification_settings import EmailRecipient


class OperationsSystemBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_name: str = Field(min_length=1, max_length=128)
    segment_duration_seconds: int = Field(ge=30, le=86400)
    remux_concurrency: int = Field(ge=1, le=16)
    rtsp_timeout_us: int = Field(ge=500_000, le=120_000_000)
    auto_start_enabled: bool
    align_segments_to_clock: bool
    storage_warning_percent: float = Field(ge=1, le=99)
    storage_critical_percent: float = Field(ge=1, le=100)
    upload_enabled: bool
    upload_concurrency: int = Field(ge=1, le=16)
    upload_retry_max: int = Field(ge=1, le=100)
    webdav_url: str = Field(max_length=1024)
    webdav_root: str = Field(max_length=512)
    webdav_username: str = Field(max_length=255)
    local_retention_hours: int = Field(ge=-1, le=87600)

    @model_validator(mode="after")
    def validate_thresholds(self):
        if self.storage_critical_percent <= self.storage_warning_percent:
            raise ValueError("磁盘严重告警阈值必须大于普通告警阈值")
        return self


class OperationsNotificationBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_enabled: bool
    offline_alert_seconds: float = Field(ge=0, le=86400)
    recovery_stable_seconds: float = Field(ge=0, le=3600)
    notify_recovery: bool
    smtp_sender_name: str = Field(default="", max_length=128)
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(ge=1, le=65535)
    smtp_auth_enabled: bool
    smtp_username: str = Field(default="", max_length=255)
    smtp_from: str = Field(default="", max_length=320)
    smtp_to: str = ""
    recipients: list[EmailRecipient] = Field(default_factory=list, max_length=16)
    smtp_use_ssl: bool
    smtp_starttls: bool
    smtp_timeout_seconds: float = Field(ge=1, le=120)
    email_attach_images: bool
    email_capture_interval_seconds: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def validate_tls_modes(self):
        if self.smtp_use_ssl and self.smtp_starttls:
            raise ValueError("SMTP SSL and STARTTLS cannot both be enabled")
        return self


class OperationsCameraBackup(CameraBase):
    model_config = ConfigDict(extra="forbid")


class OperationsConfigurationBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    created_at: datetime
    system: OperationsSystemBackup
    notifications: OperationsNotificationBackup
    cameras: list[OperationsCameraBackup] = Field(default_factory=list, max_length=500)


class OperationsRestoreResult(BaseModel):
    restored_system: bool = True
    restored_notifications: bool = True
    restored_cameras: int = 0
    skipped_cameras: list[str] = Field(default_factory=list)
