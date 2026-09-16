from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.camera_connection import CameraConnection
    from app.models.hikvision import HikDeviceMetadata
    from app.models.onvif import OnvifDeviceMetadata
    from app.models.recording import Recording


_CONNECTIVITY_STALE_SECONDS = 60.0
_FAILURE_THRESHOLD = 3


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    form_factor: Mapped[str] = mapped_column(String(32), default="unknown")
    connection_type: Mapped[str] = mapped_column(
        String(32), default="manual_rtsp", server_default="manual_rtsp", nullable=False
    )
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

    status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    _connectivity_failures: Mapped[int] = mapped_column(
        "connectivity_failures", Integer, default=0, server_default="0", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped["CameraConnection | None"] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
        uselist=False,
        single_parent=True,
        lazy="joined",
    )
    recordings: Mapped[list["Recording"]] = relationship(
        back_populates="camera", passive_deletes="all"
    )
    onvif_metadata: Mapped["OnvifDeviceMetadata | None"] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined",
    )
    hik_metadata: Mapped["HikDeviceMetadata | None"] = relationship(
        back_populates="camera",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined",
    )

    @property
    def connectivity_failures(self) -> int:
        return max(0, int(self._connectivity_failures or 0))

    @connectivity_failures.setter
    def connectivity_failures(self, value: int) -> None:
        self._connectivity_failures = max(0, int(value))

    @validates("status")
    def _sync_explicit_connectivity_status(self, _key: str, value: str) -> str:
        if value == "online":
            self.connectivity_failures = 0
        elif value in {"offline", "probe_failed"}:
            self.connectivity_failures = max(self.connectivity_failures, _FAILURE_THRESHOLD)

        camera_id = getattr(self, "id", None)
        if camera_id and value in {"online", "offline", "probe_failed"}:
            try:
                from app.services.camera_connectivity_monitor import camera_connectivity_monitor

                camera_connectivity_monitor.reconcile_manual_probe(
                    int(camera_id), success=value == "online"
                )
            except (ImportError, AttributeError):
                pass
        return value

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @property
    def connectivity_status(self) -> str:
        probed_at = self._utc(self.last_probe_at)
        if probed_at is not None:
            age = (datetime.now(timezone.utc) - probed_at).total_seconds()
            if age > _CONNECTIVITY_STALE_SECONDS:
                return "unknown"
        if self.status == "online":
            return "online"
        if self.status in {"offline", "probe_failed"}:
            return "offline"
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
