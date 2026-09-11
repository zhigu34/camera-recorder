from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recording_id: Mapped[int | None] = mapped_column(
        ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
