from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.camera import Camera


class OnvifDeviceMetadata(Base):
    __tablename__ = "onvif_device_metadata"

    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True
    )
    device_service_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    device_uuid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    profiles_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    recording_profile_token: Mapped[str] = mapped_column(String(255), nullable=False)
    preview_profile_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detection_profile_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recording_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    preview_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    detection_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    camera: Mapped["Camera"] = relationship(back_populates="onvif_metadata")
