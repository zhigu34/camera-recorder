from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CameraHealthSample(Base):
    __tablename__ = "camera_health_samples"
    __table_args__ = (
        Index("ix_camera_health_samples_camera_time", "camera_id", "sampled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sampled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_recording: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    online: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recorder_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timestamp_warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    network_warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
