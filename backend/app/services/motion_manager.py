from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.models.camera import Camera
from app.models.motion import MotionDetectionSettings, MotionEvent, MotionZone
from app.services.camera_connection_revision import connection_revision_state
from app.services.event_recording_link import (
    begin_recording_event,
    end_recording_event,
    resolve_event_recording,
)
from app.services.motion_detection import ClosedMotionEvent
from app.services.motion_worker import MotionWorker, MotionWorkerConfig
from app.services.stream_resolver import resolve_stream
from app.services.system_settings import load_runtime_settings

EnabledCameraLoader = Callable[[], Awaitable[list[int]]]
ConfigLoader = Callable[[int], Awaitable[MotionWorkerConfig | None]]
EventSink = Callable[[int, ClosedMotionEvent, np.ndarray | None], Awaitable[None]]
WorkerFactory = Callable[..., Any]

_DIAGNOSTIC_DEFAULTS: dict[str, Any] = {
    "confidence": None,
    "raw_score": None,
    "moving_area_ratio": None,
    "global_change_ratio": None,
    "primary_zone_id": None,
    "global_change": False,
}
_DIAGNOSTIC_KEYS = frozenset(_DIAGNOSTIC_DEFAULTS)


async def _default_enabled_camera_loader() -> list[int]:
    async with SessionLocal() as db:
        result = await db.scalars(
            select(MotionDetectionSettings.camera_id)
            .where(MotionDetectionSettings.enabled.is_(True))
            .order_by(MotionDetectionSettings.camera_id)
        )
        return list(result)


async def _default_config_loader(camera_id: int) -> MotionWorkerConfig | None:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        motion = await db.get(MotionDetectionSettings, camera_id)
        if camera is None or motion is None or not camera.enabled or not motion.enabled:
            return None
        runtime = await load_runtime_settings(db)
        zones_result = await db.scalars(
            select(MotionZone).where(MotionZone.camera_id == camera_id).order_by(MotionZone.id)
        )
        zones = [
            {
                "id": zone.id,
                "name": zone.name,
                "enabled": zone.enabled,
                "polygon": zone.polygon_json,
            }
            for zone in zones_result
        ]
        resolved = resolve_stream(camera, "detection")
        connection = getattr(camera, "connection", None)
        return MotionWorkerConfig(
            camera_id=camera.id,
            # Legacy discrete fields remain on the config for compatibility with
            # direct worker tests. Production execution uses stream_uri/stream below.
            ip=camera.ip,
            port=camera.rtsp_port,
            username=camera.username,
            password=decrypt_secret(camera.password_encrypted),
            main_path=camera.rtsp_path,
            sub_path=camera.sub_rtsp_path,
            rtsp_timeout_us=runtime.rtsp_timeout_us,
            analysis_fps=motion.analysis_fps,
            analysis_width=motion.analysis_width,
            sensitivity=motion.sensitivity,
            min_duration_ms=motion.min_duration_ms,
            merge_gap_ms=motion.merge_gap_ms,
            zones=zones,
            event_min_interval_ms=motion.event_min_interval_ms,
            stream_uri=resolved.uri,
            stream=resolved.role,
            connection_revision=(connection.revision if connection is not None else None),
        )


def _write_snapshot(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("failed to encode motion snapshot")
    path.write_bytes(encoded.tobytes())


async def _recording_for_event(camera_id: int, event: ClosedMotionEvent) -> int | None:
    return await resolve_event_recording(camera_id, event.started_at, event.ended_at)


async def _default_event_sink(
    camera_id: int,
    event: ClosedMotionEvent,
    frame: np.ndarray | None,
) -> None:
    recording_id = await _recording_for_event(camera_id, event)
    async with SessionLocal() as db:
        row = MotionEvent(
            camera_id=camera_id,
            zone_id=event.zone_id,
            recording_id=recording_id,
            started_at=event.started_at,
            ended_at=event.ended_at,
            peak_score=event.peak_score,
            metadata_json=json.dumps({"detector": "motion-v2"}, ensure_ascii=False),
        )
        db.add(row)
        await db.flush()

        if frame is not None:
            relative = (
                Path("motion")
                / event.started_at.strftime("%Y/%m/%d")
                / f"camera-{camera_id}"
                / f"event-{row.id}.jpg"
            )
            absolute = settings.data_dir / relative
            try:
                await asyncio.to_thread(_write_snapshot, absolute, frame)
                row.snapshot_path = str(relative)
            except Exception:
                row.snapshot_path = None

        await db.commit()


class MotionDetectionManager:
    def __init__(
        self,
        *,
        enabled_camera_loader: EnabledCameraLoader = _default_enabled_camera_loader,
        config_loader: ConfigLoader = _default_config_loader,
        event_sink: EventSink = _default_event_sink,
        worker_factory: WorkerFactory = MotionWorker,
        reconnect_delays: tuple[float, ...] = (2.0, 5.0, 10.0, 30.0),
    ) -> None:
        self.enabled_camera_loader = enabled_camera_loader
        self.config_loader = config_loader
        self.event_sink = event_sink
        self.worker_factory = worker_factory
        self.reconnect_delays = reconnect_delays or (2.0,)
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._status: dict[int, dict[str, Any]] = {}
        self._running = False

    @staticmethod
    def _default_status() -> dict[str, Any]:
        return {
            "state": "disabled",
            "stream": None,
            "last_frame_at": None,
            "last_error": None,
            **_DIAGNOSTIC_DEFAULTS,
        }

    def _set_status(
        self,
        camera_id: int,
        state: str,
        stream: str | None = None,
        last_frame_at: datetime | None = None,
        last_error: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        previous = self._status.get(camera_id, self._default_status())
        if state in {"disabled", "stopped"} and diagnostics is None:
            diagnostic_values = dict(_DIAGNOSTIC_DEFAULTS)
        else:
            diagnostic_values = {
                key: previous.get(key, default)
                for key, default in _DIAGNOSTIC_DEFAULTS.items()
            }
            if diagnostics is not None:
                for key in _DIAGNOSTIC_KEYS:
                    if key in diagnostics:
                        diagnostic_values[key] = diagnostics[key]

        resolved_stream = stream if stream is not None else previous.get("stream")
        if state in {"disabled", "stopped"} and stream is None:
            resolved_stream = None

        self._status[camera_id] = {
            "state": state,
            "stream": resolved_stream,
            "last_frame_at": (
                last_frame_at if last_frame_at is not None else previous.get("last_frame_at")
            ),
            "last_error": last_error,
            **diagnostic_values,
        }

    def status(self, camera_id: int) -> dict[str, Any]:
        return dict(self._status.get(camera_id, self._default_status()))

    def active_camera_ids(self) -> list[int]:
        return sorted(camera_id for camera_id, task in self._tasks.items() if not task.done())

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for camera_id in await self.enabled_camera_loader():
            await self.restart_camera(camera_id)

    async def stop(self) -> None:
        if not self._running and not self._tasks:
            return
        self._running = False
        camera_ids = list(self._tasks)
        for camera_id in camera_ids:
            await self.stop_camera(camera_id)

    async def stop_camera(self, camera_id: int) -> None:
        task = self._tasks.pop(camera_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._set_status(camera_id, "stopped", last_error=None)

    async def restart_camera(self, camera_id: int) -> None:
        task = self._tasks.pop(camera_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        try:
            config = await self.config_loader(camera_id)
        except Exception as exc:
            self._set_status(camera_id, "error", last_error=str(exc))
            return
        if config is None:
            self._set_status(camera_id, "disabled", stream=None, last_error=None)
            return
        if not self._running:
            self._set_status(camera_id, "stopped", stream=None, last_error=None)
            return

        self._set_status(camera_id, "starting", stream=None, last_error=None)
        self._tasks[camera_id] = asyncio.create_task(
            self._supervise(config),
            name=f"motion-camera-{camera_id}",
        )

    async def _supervise(self, config: MotionWorkerConfig) -> None:
        camera_id = config.camera_id
        attempt = 0
        while self._running:
            revision_state = await connection_revision_state(camera_id, config.connection_revision)
            if revision_state == "stale":
                self._set_status(camera_id, "stopped", stream=None, last_error=None)
                break

            def on_status(
                state: str,
                stream: str | None,
                last_frame_at: datetime | None,
                last_error: str | None,
                diagnostics: dict[str, Any] | None,
            ) -> None:
                self._set_status(
                    camera_id,
                    state,
                    stream,
                    last_frame_at,
                    last_error,
                    diagnostics,
                )

            async def on_event_started(started_at: datetime) -> None:
                begin_recording_event(camera_id, started_at)

            async def on_event(event: ClosedMotionEvent, frame: np.ndarray | None) -> None:
                try:
                    await self.event_sink(camera_id, event, frame)
                finally:
                    end_recording_event(camera_id)

            worker = self.worker_factory(config, on_event=on_event, on_status=on_status)
            worker.on_event_started = on_event_started
            try:
                await worker.run()
                if not self._running:
                    break
                raise RuntimeError("motion worker stopped unexpectedly")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                self._set_status(
                    camera_id,
                    "reconnecting",
                    stream=self.status(camera_id).get("stream"),
                    last_error=str(exc),
                )
                delay = self.reconnect_delays[min(attempt, len(self.reconnect_delays) - 1)]
                attempt += 1
                await asyncio.sleep(delay)
                self._set_status(
                    camera_id,
                    "starting",
                    stream=self.status(camera_id).get("stream"),
                    last_error=None,
                )


motion_detection_manager = MotionDetectionManager()
