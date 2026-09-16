from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.camera import Camera


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="RESTRICT"), index=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_mkv_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mp4_path: Mapped[str] = mapped_column(String(1024), unique=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    video_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="ready")
    health_status: Mapped[str] = mapped_column(String(32), default="healthy")
    ffprobe_ok: Mapped[int] = mapped_column(Integer, default=1)
    has_video: Mapped[int] = mapped_column(Integer, default=1)
    has_audio: Mapped[int] = mapped_column(Integer, default=1)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    timestamp_warning_count: Mapped[int] = mapped_column(Integer, default=0)
    network_warning_count: Mapped[int] = mapped_column(Integer, default=0)
    upload_status: Mapped[str] = mapped_column(String(32), default="pending")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    camera: Mapped["Camera"] = relationship(back_populates="recordings")
