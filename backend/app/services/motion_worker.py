from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from app.core.config import settings
from app.services.camera_preview import infer_substream_path
from app.services.camera_probe import build_rtsp_url, probe_camera, probe_stream_uri
from app.services.motion_analysis import MotionAnalysisResult, MotionFrameAnalyzer
from app.services.motion_detection import (
    ClosedMotionEvent,
    MotionConfidenceResult,
    MotionConfidenceTracker,
    MotionEventStateMachine,
    sensitivity_profile,
)

MotionStream = Literal["main", "sub"]


class MotionWorkerError(RuntimeError):
    pass


def deployment_now() -> datetime:
    name = os.getenv("TZ", "UTC").strip() or "UTC"
    try:
        zone = ZoneInfo(name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    return datetime.now(zone)


@dataclass(frozen=True, slots=True)
class MotionWorkerConfig:
    camera_id: int
    ip: str
    port: int
    username: str
    password: str
    main_path: str
    sub_path: str | None
    rtsp_timeout_us: int
    analysis_fps: int
    analysis_width: int
    sensitivity: str
    min_duration_ms: int
    merge_gap_ms: int
    zones: list[dict[str, Any]]
    event_min_interval_ms: int = 60_000
    stream_uri: str | None = None
    stream: MotionStream | None = None


def select_motion_path(main_path: str, sub_path: str | None) -> tuple[str, MotionStream]:
    """Compatibility helper; production stream selection belongs to stream_resolver."""

    configured = sub_path.strip() if sub_path else None
    if configured:
        return configured, "sub"
    inferred = infer_substream_path(main_path)
    if inferred:
        return inferred, "sub"
    return main_path, "main"


def scaled_dimensions(source_width: int, source_height: int, max_width: int) -> tuple[int, int]:
    if source_width <= 0 or source_height <= 0:
        raise ValueError("source dimensions must be positive")
    if max_width <= 0:
        raise ValueError("max_width must be positive")
    width = min(source_width, max_width)
    if width == source_width:
        height = source_height
    else:
        height = int(source_height * width / source_width)
    width = max(2, width - (width % 2))
    height = max(2, height - (height % 2))
    return width, height


def build_motion_command(
    *,
    rtsp_timeout_us: int,
    fps: int,
    width: int,
    stream_uri: str | None = None,
    ip: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    rtsp_path: str | None = None,
) -> list[str]:
    if stream_uri is None:
        if None in {ip, port, username, password, rtsp_path}:
            raise ValueError("stream_uri or complete legacy RTSP fields are required")
        stream_uri = build_rtsp_url(
            str(ip), int(port), str(username), str(password), str(rtsp_path)
        )
    return [
        settings.ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        str(rtsp_timeout_us),
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-i",
        stream_uri,
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"fps={fps},scale='min({width},iw)':-2",
        "-pix_fmt",
        "bgr24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def runtime_state_for_analysis(analysis: MotionAnalysisResult) -> str:
    if analysis.warming_up:
        return "warming_up"
    if analysis.global_change or analysis.stabilizing:
        return "stabilizing"
    return "running"


def runtime_diagnostics(
    analysis: MotionAnalysisResult,
    confidence: MotionConfidenceResult,
) -> dict[str, Any]:
    return {
        "confidence": confidence.confidence,
        "raw_score": analysis.raw_score,
        "moving_area_ratio": analysis.moving_area_ratio,
        "global_change_ratio": analysis.global_change_ratio,
        "primary_zone_id": analysis.primary_zone_id,
        "global_change": analysis.global_change,
    }


def snapshot_quality_key(
    analysis: MotionAnalysisResult,
    confidence: MotionConfidenceResult,
) -> tuple[float, float] | None:
    if (
        analysis.warming_up
        or analysis.stabilizing
        or analysis.global_change
        or analysis.raw_score <= 0.0
        or not confidence.motion
    ):
        return None
    return (confidence.confidence, analysis.raw_score)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except TimeoutError:
        process.kill()
        with suppress(Exception):
            await process.wait()


EventCallback = Callable[[ClosedMotionEvent, np.ndarray | None], Awaitable[None]]
EventStartCallback = Callable[[datetime], Awaitable[None]]
StatusCallback = Callable[
    [str, MotionStream | None, datetime | None, str | None, dict[str, Any] | None],
    None,
]


class MotionWorker:
    def __init__(
        self,
        config: MotionWorkerConfig,
        *,
        on_event: EventCallback,
        on_status: StatusCallback,
    ) -> None:
        self.config = config
        self.on_event = on_event
        self.on_status = on_status
        # The manager attaches this optional callback after worker construction so
        # existing worker factories and direct tests keep their original signature.
        self.on_event_started: EventStartCallback | None = None
        self.process: asyncio.subprocess.Process | None = None

    async def run(self) -> None:
        legacy_path: str | None = None
        if self.config.stream_uri is not None and self.config.stream is not None:
            stream_uri = self.config.stream_uri
            stream = self.config.stream
        else:
            legacy_path, stream = select_motion_path(self.config.main_path, self.config.sub_path)
            stream_uri = build_rtsp_url(
                self.config.ip,
                self.config.port,
                self.config.username,
                self.config.password,
                legacy_path,
            )

        state: MotionEventStateMachine | None = None
        best_frame: np.ndarray | None = None
        best_quality: tuple[float, float] | None = None
        last_stable_motion_at: datetime | None = None
        self.on_status("starting", stream, None, None, None)
        try:
            if self.config.stream_uri is not None:
                probe = await probe_stream_uri(
                    stream_uri=stream_uri,
                    rtsp_timeout_us=self.config.rtsp_timeout_us,
                )
            else:
                assert legacy_path is not None
                probe = await probe_camera(
                    ip=self.config.ip,
                    port=self.config.port,
                    username=self.config.username,
                    password=self.config.password,
                    rtsp_path=legacy_path,
                    rtsp_timeout_us=self.config.rtsp_timeout_us,
                )
            source_width = int(probe.get("width") or 0)
            source_height = int(probe.get("height") or 0)
            output_width, output_height = scaled_dimensions(
                source_width,
                source_height,
                self.config.analysis_width,
            )
            command = build_motion_command(
                stream_uri=stream_uri,
                rtsp_timeout_us=self.config.rtsp_timeout_us,
                fps=self.config.analysis_fps,
                width=self.config.analysis_width,
            )
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert self.process.stdout is not None
            analyzer = MotionFrameAnalyzer(
                self.config.sensitivity,
                analysis_fps=self.config.analysis_fps,
            )
            tracker = MotionConfidenceTracker(sensitivity_profile(self.config.sensitivity))
            state = MotionEventStateMachine(
                min_duration_ms=self.config.min_duration_ms,
                merge_gap_ms=self.config.merge_gap_ms,
                event_min_interval_ms=self.config.event_min_interval_ms,
            )
            frame_size = output_width * output_height * 3

            while True:
                try:
                    raw = await self.process.stdout.readexactly(frame_size)
                except asyncio.IncompleteReadError as exc:
                    if not exc.partial:
                        break
                    raise MotionWorkerError("motion stream ended with an incomplete frame") from exc

                timestamp = deployment_now()
                frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                    (output_height, output_width, 3)
                )
                analysis = analyzer.analyze(frame, self.config.zones)
                suppressed = (
                    analysis.warming_up
                    or analysis.stabilizing
                    or analysis.global_change
                )
                confidence = tracker.update(
                    analysis.raw_score,
                    suppressed=suppressed,
                )
                if not suppressed and confidence.motion:
                    last_stable_motion_at = timestamp

                was_active = state.active
                closed = state.update(
                    timestamp,
                    motion=confidence.motion,
                    score=confidence.confidence,
                    zone_id=analysis.primary_zone_id,
                    end_boundary_at=last_stable_motion_at if suppressed else None,
                )
                if not was_active and state.active and state.started_at is not None:
                    callback = self.on_event_started
                    if callback is not None:
                        await callback(state.started_at)

                for event in closed:
                    await self.on_event(event, best_frame)
                    best_frame = None
                    best_quality = None

                quality = snapshot_quality_key(analysis, confidence)
                if quality is not None and (
                    best_quality is None or quality >= best_quality
                ):
                    best_frame = frame.copy()
                    best_quality = quality
                elif not state.active and confidence.confidence <= 0.0:
                    best_frame = None
                    best_quality = None

                self.on_status(
                    runtime_state_for_analysis(analysis),
                    stream,
                    timestamp,
                    None,
                    runtime_diagnostics(analysis, confidence),
                )

            stderr = b""
            if self.process.stderr is not None:
                stderr = await self.process.stderr.read()
            message = stderr.decode(errors="replace").strip()
            raise MotionWorkerError(message[-1000:] or "motion stream ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.on_status("error", stream, None, str(exc), None)
            raise
        finally:
            if state is not None:
                for event in state.flush(deployment_now()):
                    try:
                        await self.on_event(event, best_frame)
                    except Exception:
                        # Cleanup must not mask cancellation or couple recording
                        # lifecycle to motion-event persistence failures.
                        pass
                    best_frame = None
                    best_quality = None
            if self.process is not None:
                await _stop_process(self.process)
                self.process = None
