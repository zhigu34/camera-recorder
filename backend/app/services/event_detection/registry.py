from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.schemas.event_detection import EventSourceDescriptor, EventSourceRead


class EventSourceAdapter(Protocol):
    source_id: str

    async def descriptor(
        self,
        camera: Camera,
        db: AsyncSession | None,
    ) -> EventSourceDescriptor: ...

    async def read(self, camera: Camera, db: AsyncSession) -> EventSourceRead: ...

    async def update(
        self,
        camera: Camera,
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> EventSourceRead: ...


class UnknownEventSource(KeyError):
    pass


class EventSourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, EventSourceAdapter] = {}

    def register(self, adapter: EventSourceAdapter) -> None:
        if adapter.source_id in self._sources:
            raise ValueError(f"duplicate event source: {adapter.source_id}")
        self._sources[adapter.source_id] = adapter

    def get(self, source_id: str) -> EventSourceAdapter:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise UnknownEventSource(source_id) from exc

    def ids(self) -> list[str]:
        return list(self._sources)
