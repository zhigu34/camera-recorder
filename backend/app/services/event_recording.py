from __future__ import annotations

import asyncio
import signal
import time
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.motion import MotionDetectionSettings
from app.models.recording import Recording
from app.services.media_input import media_input_from_uri
from app.services.recorder_manager import recorder_manager
from app.services.segment_processor import (
    decode_media_video,
    parse_segment_time,
    probe_media,
    safe_camera_name,
    scan_media_packets,
)
from app.services.stream_resolver import resolve_stream
from app.services.system_settings import load_runtime_settings

_EVENT_PRE_ROLL_SECONDS = 5.0
_BUFFER_SEGMENT_SECONDS = 1
_BUFFER_RETENTION_SECONDS = 30.0
_RECONCILE_SECONDS = 2.0


def event_clip_window(
    started_at: datetime,
    ended_at: datetime,
    *,
    pre_roll_seconds: float = _EVENT_PRE_ROLL_SECONDS,
) -> tuple[datetime, datetime]:
    clip_end = max(started_at, ended_at)
    return started_at - timedelta(seconds=max(0.0, pre_roll_seconds)), clip_end


def should_buffer_event_camera(
    *,
    camera_enabled: bool,
    detection_enabled: bool,
    recorder_running: bool,
) -> bool:
    return camera_enabled and detection_enabled and not recorder_running


def build_event_buffer_command(
    *,
    stream_uri: str,
    output_dir: Path,
    rtsp_timeout_us: int,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    media_input = media_input_from_uri(stream_uri, timeout_us=rtsp_timeout_us)
    return [
        settings.ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        *media_input.transport_args,
        "-fflags",
        "+discardcorrupt+genpts",
        "-use_wallclock_as_timestamps",
        "1",
        "-i",
        media_input.uri,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-f",
        "segment",
        "-segment_format",
        "matroska",
        "-segment_time",
        str(_BUFFER_SEGMENT_SECONDS),
        "-reset_timestamps",
        "1",
        "-strftime",
        "1",
        str(output_dir / "%Y-%m-%d_%H-%M-%S.mkv"),
    ]


def select_buffer_segments(
    paths: list[Path],
    clip_start: datetime,
    clip_end: datetime,
) -> list[Path]:
    """Select finalized segments beginning at/before clip_start through clip_end.

    FFmpeg's segment muxer only cuts stream-copy input on suitable packet/keyframe
    boundaries, so `segment_time=1` is a target rather than a guaranteed duration.
    Choosing the closest segment whose start is not later than the requested window
    protects the five-second pre-roll even with a long camera GOP. The clip may carry
    a little extra leading video, but it must never lose requested pre-roll frames.
    """

    ordered: list[tuple[datetime, Path]] = []
    for path in paths:
        started_at = parse_segment_time(path)
        if started_at is not None and started_at <= clip_end:
            ordered.append((started_at, path))
    ordered.sort(key=lambda item: (item[0], item[1].name))
    if not ordered:
        return []

    start_index = 0
    for index, (started_at, _path) in enumerate(ordered):
        if started_at <= clip_start:
            start_index = index
        else:
            break
    return [path for _started_at, path in ordered[start_index:]]


def _concat_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("'", "'\\''")
    return f"file '{escaped}'\n"


class EventBufferWorker:
    def __init__(self, camera_id: int, stream_uri: str, output_dir: Path, rtsp_timeout_us: int):
        self.camera_id = camera_id
        self.stream_uri = stream_uri
        self.output_dir = output_dir
        self.rtsp_timeout_us = rtsp_timeout_us
        self.task: asyncio.Task[None] | None = None
        self.process: asyncio.subprocess.Process | None = None
        self._stop = asyncio.Event()

    @property
    def running(self) -> bool:
        return bool(self.task and not self.task.done() and not self._stop.is_set())

    async def start(self) -> None:
        if self.running:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self.task = asyncio.create_task(self._run(), name=f"event-buffer-{self.camera_id}")

    async def stop(self) -> None:
        self._stop.set()
        process = self.process
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                process.kill()
                with suppress(Exception):
                    await process.wait()
        task = self.task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self.process = None
        self.task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                command = build_event_buffer_command(
                    stream_uri=self.stream_uri,
                    output_dir=self.output_dir,
                    rtsp_timeout_us=self.rtsp_timeout_us,
                )
                self.process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await self.process.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                self.process = None
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=3.0)
            except TimeoutError:
                pass


class EventRecordingManager:
    def __init__(self) -> None:
        self._workers: dict[int, EventBufferWorker] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._capture_locks: dict[int, asyncio.Lock] = {}
        self._worker_lock = asyncio.Lock()
        self._pinned_since: dict[int, datetime] = {}
        self.buffer_root = settings.data_dir / "event-buffer"

    def begin_event(self, camera_id: int, started_at: datetime) -> None:
        """Pin the ring from five seconds before a confirmed event begins."""

        pinned_at, _ = event_clip_window(started_at, started_at)
        existing = self._pinned_since.get(camera_id)
        if existing is None or pinned_at < existing:
            self._pinned_since[camera_id] = pinned_at

    def end_event(self, camera_id: int) -> None:
        self._pinned_since.pop(camera_id, None)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self.buffer_root.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        await self.reconcile_once()
        self._task = asyncio.create_task(self._run(), name="event-recording-manager")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._task = None
        async with self._worker_lock:
            for camera_id in list(self._workers):
                await self._stop_camera_unlocked(camera_id)
        self._pinned_since.clear()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_RECONCILE_SECONDS)
            except TimeoutError:
                pass

    async def _stop_camera_unlocked(self, camera_id: int) -> None:
        worker = self._workers.pop(camera_id, None)
        if worker is not None:
            await worker.stop()

    async def stop_camera(self, camera_id: int) -> None:
        async with self._worker_lock:
            await self._stop_camera_unlocked(camera_id)

    async def reconcile_once(self) -> int:
        async with SessionLocal() as db:
            runtime = await load_runtime_settings(db)
            cameras = list(
                await db.scalars(
                    select(Camera)
                    .join(MotionDetectionSettings, MotionDetectionSettings.camera_id == Camera.id)
                    .where(
                        Camera.enabled.is_(True),
                        MotionDetectionSettings.enabled.is_(True),
                    )
                    .order_by(Camera.id)
                )
            )

        eligible: dict[int, tuple[Camera, str]] = {}
        for camera in cameras:
            if not should_buffer_event_camera(
                camera_enabled=camera.enabled,
                detection_enabled=True,
                recorder_running=recorder_manager.is_running(camera.id),
            ):
                continue
            try:
                stream_uri = resolve_stream(camera, "recording").uri
            except Exception:
                continue
            eligible[camera.id] = (camera, stream_uri)

        async with self._worker_lock:
            for camera_id in list(self._workers):
                if camera_id not in eligible:
                    await self._stop_camera_unlocked(camera_id)

            for camera_id, (_camera, stream_uri) in eligible.items():
                worker = self._workers.get(camera_id)
                if worker is not None and worker.running and worker.stream_uri == stream_uri:
                    self._cleanup_ring(camera_id, worker.output_dir)
                    continue
                if worker is not None:
                    await self._stop_camera_unlocked(camera_id)
                output_dir = self.buffer_root / f"camera-{camera_id}"
                worker = EventBufferWorker(camera_id, stream_uri, output_dir, runtime.rtsp_timeout_us)
                self._workers[camera_id] = worker
                await worker.start()
                self._cleanup_ring(camera_id, output_dir)
        return len(eligible)

    def _cleanup_ring(self, camera_id: int, output_dir: Path) -> None:
        files = sorted(output_dir.glob("*.mkv"), key=lambda path: path.stat().st_mtime)
        if len(files) <= 1:
            return
        cutoff = time.time() - _BUFFER_RETENTION_SECONDS
        pinned_since = self._pinned_since.get(camera_id)

        preserve_from: datetime | None = None
        if pinned_since is not None:
            parsed = sorted(
                (
                    (started_at, path)
                    for path in files
                    if (started_at := parse_segment_time(path)) is not None
                ),
                key=lambda item: (item[0], item[1].name),
            )
            if parsed:
                preserve_from = parsed[0][0]
                for started_at, _path in parsed:
                    if started_at <= pinned_since:
                        preserve_from = started_at
                    else:
                        break

        for path in files[:-1]:
            try:
                started_at = parse_segment_time(path)
                if preserve_from is not None and started_at is not None and started_at >= preserve_from:
                    continue
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    async def capture(
        self,
        camera_id: int,
        started_at: datetime,
        ended_at: datetime,
    ) -> int | None:
        if recorder_manager.is_running(camera_id):
            return None
        lock = self._capture_locks.setdefault(camera_id, asyncio.Lock())
        async with lock:
            if recorder_manager.is_running(camera_id):
                return None

            # Gracefully stop the ring FFmpeg long enough to finalize its current MKV.
            # Reading the active file directly can truncate the event tail. Restart it
            # immediately after taking the immutable segment snapshot, before remuxing.
            async with self._worker_lock:
                worker = self._workers.get(camera_id)
                if worker is None or not worker.running:
                    return None
                await worker.stop()
                try:
                    clip_start, clip_end = event_clip_window(started_at, ended_at)
                    segments = select_buffer_segments(
                        list(worker.output_dir.glob("*.mkv")),
                        clip_start,
                        clip_end,
                    )
                finally:
                    if not recorder_manager.is_running(camera_id) and not self._stop.is_set():
                        await worker.start()

            if not segments:
                return None
            first_start = parse_segment_time(segments[0])
            if first_start is None:
                return None
            duration = max(0.1, (clip_end - first_start).total_seconds())
            return await self._materialize_clip(
                camera_id=camera_id,
                segments=segments,
                started_at=first_start,
                requested_duration=duration,
            )

    async def _materialize_clip(
        self,
        *,
        camera_id: int,
        segments: list[Path],
        started_at: datetime,
        requested_duration: float,
    ) -> int | None:
        async with SessionLocal() as db:
            camera = await db.get(Camera, camera_id)
            if camera is None:
                return None
            safe_name = safe_camera_name(camera.name)
            date_dir = started_at.strftime("%Y-%m-%d")
            filename = f"{safe_name}_{started_at.strftime('%Y-%m-%d_%H-%M-%S_%f')}_event.mp4"
            target = settings.recordings_dir / safe_name / date_dir / filename
            existing = await db.scalar(select(Recording).where(Recording.mp4_path == str(target)))
            if existing is not None and target.exists():
                return int(existing.id)
            video_codec = camera.video_codec

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.part.mp4")
        concat_file = self.buffer_root / f"camera-{camera_id}" / (
            f".concat-{started_at.strftime('%Y%m%d%H%M%S%f')}.txt"
        )
        temporary.unlink(missing_ok=True)
        concat_file.write_text("".join(_concat_line(path) for path in segments), encoding="utf-8")
        command = [
            settings.ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-t",
            f"{requested_duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
        ]
        if video_codec == "hevc":
            command += ["-tag:v", "hvc1"]
        command += [
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            "-y",
            str(temporary),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(stderr.decode(errors="replace").strip() or "event clip remux failed")
            temporary.replace(target)
            media = await probe_media(target)
            if not media["has_video"]:
                raise RuntimeError("event clip has no video stream")
            packet_ok, _packet_error = await scan_media_packets(target)
            warning_count = 0
            health = "healthy"
            if not packet_ok:
                warning_count += 1
                health = "warning"
                decode_ok, _decode_error = await decode_media_video(target)
                if not decode_ok:
                    warning_count += 1
                    health = "unhealthy"

            media_duration = media["duration"] or requested_duration
            async with SessionLocal() as db:
                recording = Recording(
                    camera_id=camera_id,
                    started_at=started_at,
                    ended_at=started_at + timedelta(seconds=media_duration),
                    duration=media_duration,
                    source_mkv_path=None,
                    mp4_path=str(target),
                    file_size=target.stat().st_size,
                    video_codec=media["video_codec"],
                    audio_codec=media["audio_codec"],
                    width=media["width"],
                    height=media["height"],
                    fps=media["fps"],
                    status="ready",
                    health_status=health,
                    ffprobe_ok=1,
                    has_video=int(media["has_video"]),
                    has_audio=int(media["has_audio"]),
                    warning_count=warning_count,
                )
                db.add(recording)
                await db.commit()
                await db.refresh(recording)
                return int(recording.id)
        except Exception:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            return None
        finally:
            concat_file.unlink(missing_ok=True)

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._task and not self._task.done()),
            "active_camera_ids": sorted(
                camera_id for camera_id, worker in self._workers.items() if worker.running
            ),
            "pinned_camera_ids": sorted(self._pinned_since),
            "pre_roll_seconds": _EVENT_PRE_ROLL_SECONDS,
            "retention_seconds": _BUFFER_RETENTION_SECONDS,
        }


event_recording_manager = EventRecordingManager()
