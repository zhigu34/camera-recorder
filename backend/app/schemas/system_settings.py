from pydantic import BaseModel, Field, model_validator


class SystemSettingsRead(BaseModel):
    app_name: str
    segment_duration_seconds: int
    remux_concurrency: int
    rtsp_timeout_us: int
    auto_start_enabled: bool
    align_segments_to_clock: bool
    storage_warning_percent: float
    storage_critical_percent: float
    upload_enabled: bool
    upload_concurrency: int
    upload_retry_max: int
    webdav_url: str
    webdav_root: str
    webdav_username: str
    webdav_password_set: bool
    local_retention_hours: int


class SystemSettingsUpdate(BaseModel):
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
    webdav_password: str | None = Field(default=None, max_length=2048)
    clear_webdav_password: bool = False
    local_retention_hours: int = Field(ge=-1, le=87600)

    @model_validator(mode="after")
    def validate_thresholds(self):
        if self.storage_critical_percent <= self.storage_warning_percent:
            raise ValueError("磁盘严重告警阈值必须大于普通告警阈值")
        return self
