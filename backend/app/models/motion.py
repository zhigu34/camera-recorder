from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MotionDetectionSettings(Base):
    __tablename__ = "motion_detection_settings"

    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    analysis_fps: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    analysis_width: Mapped[int] = mapped_column(Integer, default=640, nullable=False)
    min_duration_ms: Mapped[int] = mapped_column(Integer, default=800, nullable=False)
    merge_gap_ms: Mapped[int] = mapped_column(Integer, default=3000, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MotionZone(Base):
    __tablename__ = "motion_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    polygon_json: Mapped[list[list[float]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def polygon(self) -> list[list[float]]:
        return self.polygon_json


class MotionEvent(Base):
    __tablename__ = "motion_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("motion_zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recording_id: Mapped[int | None] = mapped_column(
        ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    peak_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
