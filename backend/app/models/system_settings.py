from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    app_name: Mapped[str] = mapped_column(String(128), default="Camera Recorder", nullable=False)

    segment_duration_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    remux_concurrency: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    rtsp_timeout_us: Mapped[int] = mapped_column(Integer, default=5_000_000, nullable=False)
    auto_start_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    align_segments_to_clock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    storage_warning_percent: Mapped[float] = mapped_column(Float, default=80.0, nullable=False)
    storage_critical_percent: Mapped[float] = mapped_column(Float, default=90.0, nullable=False)

    upload_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    upload_concurrency: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    upload_retry_max: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    webdav_url: Mapped[str] = mapped_column(
        String(1024), default="http://openlist:5244/dav", nullable=False
    )
    webdav_root: Mapped[str] = mapped_column(String(512), default="监控录像", nullable=False)
    webdav_username: Mapped[str] = mapped_column(String(255), default="admin", nullable=False)
    webdav_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_retention_hours: Mapped[int] = mapped_column(Integer, default=48, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )