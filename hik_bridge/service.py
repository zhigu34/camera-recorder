from __future__ import annotations

import asyncio
import queue
import secrets
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol


class HikBridgeError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None) -> None:
        self.code = code
        suffix = f" (SDK error {code})" if code is not None else ""
        super().__init__(f"{message}{suffix}")


class HikSdkProtocol(Protocol):
    runtime_available: bool

    def initialize(self) -> None: ...
    def cleanup(self) -> None: ...
    def login(
        self, host: str, port: int, username: str, password: str
    ) -> tuple[int, dict[str, Any]]: ...
    def logout(self, user_id: int) -> None: ...
    def start_realplay(self, user_id: int, channel: int, stream_type: int, callback) -> int: ...
    def stop_realplay(self, handle: int) -> None: ...


@dataclass(slots=True, frozen=True)
class StreamRequest:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    channel: int = 1
    stream_type: int = 0


_CLOSE_SENTINEL = object()


@dataclass(slots=True)
class _Session:
    stream_id: str
    user_id: int
    play_handle: int
    callback: Any
    chunks: queue.Queue[bytes | object]
    overflowed: bool = False
    closed: bool = False


class HikBridgeService:
    def __init__(self, sdk: HikSdkProtocol, *, queue_size: int = 256) -> None:
        self.sdk = sdk
        self.queue_size = max(1, queue_size)
        self._sessions: dict[str, _Session] = {}
        self._started = False
        self._runtime_ready = False
        self._runtime_error: str | None = None

    @property
    def runtime_available(self) -> bool:
        return self._runtime_ready

    async def start(self) -> None:
        if self._started:
            return

        self._runtime_ready = False
        self._runtime_error = None
        if self.sdk.runtime_available:
            try:
                await asyncio.to_thread(self.sdk.initialize)
                self._runtime_ready = True
            except Exception as exc:
                # A partial or incompatible proprietary runtime must never prevent
                # manual RTSP / ONVIF users from starting the application. Keep the
                # bridge healthy in degraded mode and surface the SDK failure only
                # when a HIK operation is attempted.
                self._runtime_error = str(exc)[-500:] or exc.__class__.__name__
                with suppress(Exception):
                    await asyncio.to_thread(self.sdk.cleanup)
        else:
            self._runtime_error = "HCNetSDK runtime is unavailable"
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        for stream_id in list(self._sessions):
            await self.stop_stream(stream_id)
        if self._runtime_ready:
            await asyncio.to_thread(self.sdk.cleanup)
        self._runtime_ready = False
        self._started = False

    def _require_runtime(self) -> None:
        if self._runtime_ready:
            return
        if self._runtime_error == "HCNetSDK runtime is unavailable":
            raise HikBridgeError(self._runtime_error)
        if self._runtime_error:
            raise HikBridgeError(
                f"HCNetSDK runtime initialization failed: {self._runtime_error}"
            )
        raise HikBridgeError("HCNetSDK runtime is unavailable")

    async def probe(
        self, host: str, port: int, username: str, password: str
    ) -> dict[str, Any]:
        self._require_runtime()
        user_id = -1
        try:
            user_id, info = await asyncio.to_thread(
                self.sdk.login, host, port, username, password
            )
            return dict(info)
        finally:
            if user_id >= 0:
                await asyncio.to_thread(self.sdk.logout, user_id)

    async def create_stream(self, request: StreamRequest) -> str:
        self._require_runtime()
        user_id = -1
        try:
            user_id, _info = await asyncio.to_thread(
                self.sdk.login,
                request.host,
                request.port,
                request.username,
                request.password,
            )
            chunks: queue.Queue[bytes | object] = queue.Queue(maxsize=self.queue_size)
            state: dict[str, Any] = {"session": None}

            def on_data(data: bytes) -> None:
                session: _Session | None = state["session"]
                if session is None or session.closed or not data:
                    return
                try:
                    session.chunks.put_nowait(bytes(data))
                except queue.Full:
                    session.overflowed = True

            play_handle = await asyncio.to_thread(
                self.sdk.start_realplay,
                user_id,
                request.channel,
                request.stream_type,
                on_data,
            )
            stream_id = secrets.token_urlsafe(24)
            session = _Session(stream_id, user_id, play_handle, on_data, chunks)
            state["session"] = session
            self._sessions[stream_id] = session
            return stream_id
        except Exception:
            if user_id >= 0:
                await asyncio.to_thread(self.sdk.logout, user_id)
            raise

    def require_stream(self, stream_id: str) -> None:
        session = self._sessions.get(stream_id)
        if session is None or session.closed:
            raise HikBridgeError("stream session not found")

    async def iter_stream(self, stream_id: str) -> AsyncIterator[bytes]:
        self.require_stream(stream_id)
        session = self._sessions[stream_id]
        try:
            while not session.closed:
                chunk = await asyncio.to_thread(session.chunks.get)
                if chunk is _CLOSE_SENTINEL:
                    break
                if chunk:
                    yield chunk
                if session.overflowed:
                    break
        finally:
            await self.stop_stream(stream_id)

    async def stop_stream(self, stream_id: str) -> None:
        session = self._sessions.pop(stream_id, None)
        if session is None or session.closed:
            return
        session.closed = True
        # Wake a consumer that may currently be blocked waiting for SDK bytes.
        # If the queue is full, discard one stale chunk to guarantee room for
        # the close marker; on shutdown preserving every queued byte is not useful.
        try:
            session.chunks.put_nowait(_CLOSE_SENTINEL)
        except queue.Full:
            with suppress(queue.Empty):
                session.chunks.get_nowait()
            with suppress(queue.Full):
                session.chunks.put_nowait(_CLOSE_SENTINEL)
        try:
            await asyncio.to_thread(self.sdk.stop_realplay, session.play_handle)
        finally:
            await asyncio.to_thread(self.sdk.logout, session.user_id)
