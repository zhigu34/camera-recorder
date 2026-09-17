from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

SessionCloser = Callable[[], Awaitable[None]]
logger = logging.getLogger(__name__)


class CameraMediaSessionRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[int, dict[str, SessionCloser]] = {}

    async def register(self, camera_id: int, closer: SessionCloser) -> str:
        session_id = uuid4().hex
        async with self._lock:
            self._sessions.setdefault(camera_id, {})[session_id] = closer
        return session_id

    async def unregister(self, camera_id: int, session_id: str) -> None:
        async with self._lock:
            sessions = self._sessions.get(camera_id)
            if not sessions:
                return
            sessions.pop(session_id, None)
            if not sessions:
                self._sessions.pop(camera_id, None)

    async def active_count(self, camera_id: int) -> int:
        async with self._lock:
            return len(self._sessions.get(camera_id, {}))

    async def _close_detached(
        self,
        camera_id: int,
        sessions: dict[str, SessionCloser],
    ) -> None:
        for session_id, closer in sessions.items():
            try:
                await closer()
            except Exception:
                logger.exception(
                    "failed to close camera media session",
                    extra={"camera_id": camera_id, "session_id": session_id},
                )

    async def stop_camera(self, camera_id: int) -> None:
        async with self._lock:
            sessions = self._sessions.pop(camera_id, {})
        await self._close_detached(camera_id, sessions)

    async def stop_all(self) -> None:
        async with self._lock:
            detached = self._sessions
            self._sessions = {}
        for camera_id, sessions in detached.items():
            await self._close_detached(camera_id, sessions)


camera_media_session_registry = CameraMediaSessionRegistry()
