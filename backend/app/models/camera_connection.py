from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.camera import Camera
    from app.models.hikvision import HikConnectionConfig
    from app.models.onvif_connection import OnvifConnectionConfig


class CameraConnection(Base):
    __tablename__ = "camera_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False, default="admin")
    password_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32), default="unverified", server_default="unverified", nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    camera: Mapped["Camera"] = relationship(back_populates="connection")
    rtsp_config: Mapped["RtspConnectionConfig | None"] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined",
    )
    onvif_config: Mapped["OnvifConnectionConfig | None"] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined",
    )
    hik_config: Mapped["HikConnectionConfig | None"] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined",
    )


class RtspConnectionConfig(Base):
    __tablename__ = "rtsp_connection_configs"

    connection_id: Mapped[int] = mapped_column(
        ForeignKey("camera_connections.id", ondelete="CASCADE"), primary_key=True
    )
    port: Mapped[int] = mapped_column(Integer, default=554, server_default="554", nullable=False)
    main_path: Mapped[str] = mapped_column(String(255), nullable=False)
    sub_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    connection: Mapped[CameraConnection] = relationship(back_populates="rtsp_config")
