from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.camera import Camera
    from app.models.camera_connection import CameraConnection


class HikConnectionConfig(Base):
    __tablename__ = "hik_connection_configs"

    connection_id: Mapped[int] = mapped_column(
        ForeignKey("camera_connections.id", ondelete="CASCADE"), primary_key=True
    )
    sdk_port: Mapped[int] = mapped_column(
        Integer, default=8000, server_default="8000", nullable=False
    )
    channel: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    main_stream_type: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    sub_stream_type: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    device_serial: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped["CameraConnection"] = relationship(back_populates="hik_config")


class HikDeviceMetadata(Base):
    __tablename__ = "hik_device_metadata"

    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True
    )
    sdk_port: Mapped[int] = mapped_column(
        Integer, default=8000, server_default="8000", nullable=False
    )
    channel: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    main_stream_type: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    sub_stream_type: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    device_serial: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    camera: Mapped["Camera"] = relationship(back_populates="hik_metadata")
