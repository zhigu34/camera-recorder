from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    offline_alert_seconds: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)
    recovery_stable_seconds: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    notify_recovery: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    smtp_sender_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    smtp_host: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, nullable=False)
    smtp_auth_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    smtp_username: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    smtp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_from: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    smtp_to: Mapped[str] = mapped_column(Text, default="", nullable=False)
    smtp_recipients_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    smtp_use_ssl: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    smtp_starttls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    smtp_timeout_seconds: Mapped[float] = mapped_column(Float, default=15.0, nullable=False)
    email_attach_images: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_capture_interval_seconds: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
