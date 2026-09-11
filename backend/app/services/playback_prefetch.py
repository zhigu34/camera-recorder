from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select

from app.core.database import SessionLocal
from app.models.recording import Recording
from app.models.upload import UploadTask
from app.services.cloud_playback import cloud_playback_manager
from app.services.cloud_stream import openlist_cloud_streamer
from app.services.recording_playback import recording_playback_manager
from app.services.system_settings import load_runtime_settings

_STREAM_RE = re.compile(r"^/api/recordings/(\d+)/(stream|proxy-live\.mp4|cloud-stream)$")
_PREFETCH_LEAD_SECONDS = 45.0
_DIRECT_LINK_TTL_SECONDS = 120.0
_ARM_DEDUPE_SECONDS = 30.0
_LATENCY_SAMPLES = 200


@dataclass(slots=True)
class WarmedDirectLink:
    url: str
    expires_at: float
    warmed_at: float


class PlaybackPrefetchManager:
    """Prewarm the next cloud-only recording without downloading the MP4.

    A playback request arms one delayed task per camera. Near the end of the
    current segment, the task resolves the next truly playable recording. If that
    recording only exists in OpenList/115, it performs a tiny Range probe and
    caches a provider/CDN redirect for a short period. The next cloud playback can
    then redirect immediately without repeating the OpenList lookup.
    """

    def __init__(self) -> None:
        self._camera_tasks: dict[int, asyncio.Task[None]] = {}
        self._camera_current: dict[int, int] = {}
        self._armed: dict[int, float] = {}
        self._direct_links: dict[int, WarmedDirectLink] = {}
        self._latencies: dict[str, deque[float]] = {
            "stream": deque(maxlen=_LATENCY_SAMPLES),
            "cloud": deque(maxlen=_LATENCY_SAMPLES),
            "proxy": deque(maxlen=_LATENCY_SAMPLES),
            "prefetch": deque(maxlen=_LATENCY_SAMPLES),
        }
        self._counters: dict[str, int] = {
            "scheduled": 0,
            "cloud_candidates": 0,
            "success": 0,
            "direct_links": 0,
            "direct_hits": 0,
            "range_ready": 0,
            "failures": 0,
            "cancelled": 0,
        }

    def arm(self, recording_id: int) -> None:
        now = time.monotonic()
        previous = self._armed.get(recording_id)
        if previous is not None and now - previous < _ARM_DEDUPE_SECONDS:
            return
        self._armed[recording_id] = now
        asyncio.create_task(self._arm_async(recording_id), name=f"playback-prefetch-arm-{recording_id}")

    async def _arm_async(self, recording_id: int) -> None:
        try:
            async with SessionLocal() as db:
                current = await db.get(Recording, recording_id)
                if current is None or current.started_at is None:
                    return
                camera_id = current.camera_id
                existing = self._camera_tasks.get(camera_id)
                if (
                    existing
                    and not existing.done()
                    and self._camera_current.get(camera_id) == recording_id
                ):
                    return
                if existing and not existing.done():
                    existing.cancel()
                    self._counters["cancelled"] += 1

                next_recording, upload = await self._next_cloud_only(current, db)
                if next_recording is None or upload is None:
                    self._camera_current[camera_id] = recording_id
                    return

                self._counters["cloud_candidates"] += 1
                delay = max(0.0, float(current.duration or 0) - _PREFETCH_LEAD_SECONDS)
                task = asyncio.create_task(
                    self._delayed_warm(
                        camera_id=camera_id,
                        current_recording_id=recording_id,
                        next_recording_id=next_recording.id,
                        remote_path=upload.remote_path,
                        delay=delay,
                    ),
                    name=f"playback-prefetch-{camera_id}-{next_recording.id}",
                )
                self._camera_tasks[camera_id] = task
                self._camera_current[camera_id] = recording_id
                self._counters["scheduled"] += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            self._counters["failures"] += 1

    async def _next_cloud_only(
        self,
        current: Recording,
        db,
    ) -> tuple[Recording | None, UploadTask | None]:
        boundary = or_(
            Recording.started_at > current.started_at,
            and_(Recording.started_at == current.started_at, Recording.id > current.id),
        )
        candidates = list(
            await db.scalars(
                select(Recording)
                .where(
                    Recording.camera_id == current.camera_id,
                    Recording.started_at.is_not(None),
                    boundary,
                )
                .order_by(Recording.started_at.asc(), Recording.id.asc())
                .limit(500)
            )
        )
        for candidate in candidates:
            local = Path(candidate.mp4_path)
            cloud_cache = cloud_playback_manager.source_path(candidate.id)
            proxy_ready = recording_playback_manager.status(
                candidate.id, candidate.video_codec
            )["state"] == "ready"
            if local.exists() or cloud_cache.exists() or proxy_ready:
                # This is the actual next playable segment and it is already local,
                # so there is no cloud link worth warming beyond it.
                return None, None
            if candidate.upload_status != "success":
                continue
            upload = await db.scalar(
                select(UploadTask).where(
                    UploadTask.recording_id == candidate.id,
                    UploadTask.status == "success",
                )
            )
            if upload is not None:
                return candidate, upload
        return None, None

    async def _delayed_warm(
        self,
        *,
        camera_id: int,
        current_recording_id: int,
        next_recording_id: int,
        remote_path: str,
        delay: float,
    ) -> None:
        try:
            if delay:
                await asyncio.sleep(delay)
            if self._camera_current.get(camera_id) != current_recording_id:
                return

            started = time.monotonic()
            async with SessionLocal() as db:
                runtime = await load_runtime_settings(db)
            handle = await openlist_cloud_streamer.open(
                remote_path,
                runtime,
                range_header="bytes=0-0",
                follow_redirects=False,
            )
            try:
                direct = openlist_cloud_streamer.public_redirect(handle)
                if direct:
                    now = time.monotonic()
                    self._direct_links[next_recording_id] = WarmedDirectLink(
                        url=direct,
                        expires_at=now + _DIRECT_LINK_TTL_SECONDS,
                        warmed_at=now,
                    )
                    self._counters["direct_links"] += 1
                else:
                    self._counters["range_ready"] += 1
                self._counters["success"] += 1
                self.record_latency("prefetch", (time.monotonic() - started) * 1000)
            finally:
                await handle.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._counters["failures"] += 1
        finally:
            task = self._camera_tasks.get(camera_id)
            if task is asyncio.current_task():
                self._camera_tasks.pop(camera_id, None)

    def cached_direct_link(self, recording_id: int) -> str | None:
        item = self._direct_links.get(recording_id)
        if item is None:
            return None
        if item.expires_at <= time.monotonic():
            self._direct_links.pop(recording_id, None)
            return None
        return item.url

    def note_direct_hit(self, recording_id: int) -> None:
        if recording_id in self._direct_links:
            self._counters["direct_hits"] += 1

    def record_latency(self, kind: str, milliseconds: float) -> None:
        bucket = self._latencies.get(kind)
        if bucket is not None and milliseconds >= 0:
            bucket.append(round(milliseconds, 3))

    @staticmethod
    def _latency_summary(values: deque[float]) -> dict[str, float | int | None]:
        if not values:
            return {"samples": 0, "avg_ms": None, "p95_ms": None, "max_ms": None}
        ordered = sorted(values)
        p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
        return {
            "samples": len(ordered),
            "avg_ms": round(sum(ordered) / len(ordered), 2),
            "p95_ms": round(ordered[p95_index], 2),
            "max_ms": round(ordered[-1], 2),
        }

    def snapshot(self) -> dict[str, Any]:
        # Opportunistically prune stale direct links whenever metrics are read.
        for recording_id in list(self._direct_links):
            self.cached_direct_link(recording_id)
        return {
            "prefetch": {
                **self._counters,
                "active_tasks": sum(1 for task in self._camera_tasks.values() if not task.done()),
                "cached_direct_links": len(self._direct_links),
                "lead_seconds": _PREFETCH_LEAD_SECONDS,
                "direct_link_ttl_seconds": _DIRECT_LINK_TTL_SECONDS,
                "probe_latency": self._latency_summary(self._latencies["prefetch"]),
            },
            "backend_response": {
                kind: self._latency_summary(self._latencies[kind])
                for kind in ("stream", "cloud", "proxy")
            },
        }

    async def stop(self) -> None:
        tasks = [task for task in self._camera_tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._camera_tasks.clear()
        self._camera_current.clear()


playback_prefetch_manager = PlaybackPrefetchManager()


class PlaybackPrefetchMiddleware:
    """ASGI middleware that arms prefetch and measures backend playback response latency."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        match = _STREAM_RE.match(path)
        if not match:
            await self.app(scope, receive, send)
            return

        recording_id = int(match.group(1))
        endpoint = match.group(2)
        kind = "cloud" if endpoint == "cloud-stream" else "proxy" if endpoint == "proxy-live.mp4" else "stream"

        if endpoint == "cloud-stream":
            direct = playback_prefetch_manager.cached_direct_link(recording_id)
            if direct:
                playback_prefetch_manager.note_direct_hit(recording_id)
                playback_prefetch_manager.record_latency("cloud", 0.0)
                headers = [
                    (b"location", direct.encode("utf-8")),
                    (b"cache-control", b"no-store"),
                    (b"x-cloud-playback", b"openlist-prefetch-direct"),
                    (b"x-playback-prefetch", b"hit"),
                ]
                await send({"type": "http.response.start", "status": 302, "headers": headers})
                await send({"type": "http.response.body", "body": b""})
                return
        else:
            playback_prefetch_manager.arm(recording_id)

        started = time.monotonic()
        measured = False

        async def measured_send(message) -> None:
            nonlocal measured
            if not measured:
                if message["type"] == "http.response.body" and message.get("body"):
                    measured = True
                    playback_prefetch_manager.record_latency(
                        kind, (time.monotonic() - started) * 1000
                    )
                elif message["type"] == "http.response.start" and message.get("status", 200) in {301, 302, 303, 307, 308}:
                    measured = True
                    playback_prefetch_manager.record_latency(
                        kind, (time.monotonic() - started) * 1000
                    )
            await send(message)

        await self.app(scope, receive, measured_send)
