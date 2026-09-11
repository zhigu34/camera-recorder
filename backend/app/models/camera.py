from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.recording import Recording


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    ip: Mapped[str] = mapped_column(String(255), index=True)
    rtsp_port: Mapped[int] = mapped_column(Integer, default=554)
    username: Mapped[str] = mapped_column(String(128), default="admin")
    password_encrypted: Mapped[str] = mapped_column(String(1024))
    rtsp_path: Mapped[str] = mapped_column(String(255), default="/ch1/main")
    sub_rtsp_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_record: Mapped[bool] = mapped_column(Boolean, default=False)
    recording_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    recording_schedule: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    timestamp_mode: Mapped[str] = mapped_column(String(32), default="reconstruct")

    video_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    video_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps_den: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pixel_format: Mapped[str | None] = mapped_column(String(64), nullable=True)
    has_b_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_time_base: Mapped[str | None] = mapped_column(String(32), nullable=True)

    audio_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audio_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_frame_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Kept for API/database compatibility. From now on this field is owned only
    # by connectivity probing and represents unknown/online/offline. Recorder and
    # schedule state are exposed independently through the properties below.
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    recordings: Mapped[list["Recording"]] = relationship(
        back_populates="camera", cascade="all, delete-orphan"
    )

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @property
    def connectivity_status(self) -> str:
        """Connectivity result owned by Probe, independent of recording/schedule state."""

        if self.status == "online":
            return "online"
        if self.status in {"offline", "probe_failed"}:
            return "offline"

        # Recover a correct value for rows whose legacy status was overwritten by
        # recorder/scheduler values such as recording, stopped or scheduled.
        probed_at = self._utc(self.last_probe_at)
        if probed_at is None:
            return "unknown"
        online_at = self._utc(self.last_online_at)
        if online_at is not None and online_at >= probed_at:
            return "online"
        return "offline"

    @property
    def recorder_state(self) -> str:
        from app.services.recorder_manager import recorder_manager

        snapshot = recorder_manager.status(self.id)
        return str(snapshot.get("state", "STOPPED")) if isinstance(snapshot, dict) else "STOPPED"

    @property
    def schedule_state(self) -> str:
        from app.services.recording_schedule_manager import recording_schedule_manager

        return recording_schedule_manager.state_for(self)
