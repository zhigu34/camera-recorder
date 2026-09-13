from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import cv2
import numpy as np

from app.core.config import settings
from app.services.camera_preview import infer_substream_path
from app.services.camera_probe import build_rtsp_url, probe_camera
from app.services.motion_detection import ClosedMotionEvent, MotionEventStateMachine, sensitivity_profile, zones_for_point

MotionStream = Literal["main", "sub"]


class MotionWorkerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MotionFrameResult:
    motion: bool
    score: float
    zone_ids: list[int | None]


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


def select_motion_path(main_path: str, sub_path: str | None) -> tuple[str, MotionStream]:
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
    ip: str,
    port: int,
    username: str,
    password: str,
    rtsp_path: str,
    rtsp_timeout_us: int,
    fps: int,
    width: int,
) -> list[str]:
    url = build_rtsp_url(ip, port, username, password, rtsp_path)
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
        url,
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


class MotionFrameAnalyzer:
    def __init__(self, sensitivity: str) -> None:
        profile = sensitivity_profile(sensitivity)
        self.profile = profile
        self.background = cv2.createBackgroundSubtractorMOG2(
            history=120,
            varThreshold=profile.var_threshold,
            detectShadows=False,
        )
        self.kernel = np.ones((3, 3), dtype=np.uint8)

    def analyze(self, frame: np.ndarray, zones: list[dict[str, Any]]) -> MotionFrameResult:
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("motion frames must use BGR channel layout")

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        foreground = self.background.apply(gray)
        foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, self.kernel, iterations=1)
        foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, self.kernel, iterations=2)

        contours, _ = cv2.findContours(foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frame_area = float(frame.shape[0] * frame.shape[1])
        min_area = frame_area * self.profile.min_area_ratio
        matched_zones: list[int | None] = []
        moving_area = 0.0

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < min_area:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            center = (
                (x + width / 2) / frame.shape[1],
                (y + height / 2) / frame.shape[0],
            )
            zone_ids = zones_for_point(center, zones)
            if not zone_ids:
                continue
            moving_area += area
            for zone_id in zone_ids:
                if zone_id not in matched_zones:
                    matched_zones.append(zone_id)

        score = min(1.0, moving_area / frame_area) if frame_area else 0.0
        return MotionFrameResult(
            motion=bool(matched_zones),
            score=score,
            zone_ids=matched_zones,
        )


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
StatusCallback = Callable[[str, MotionStream | None, datetime | None, str | None], None]


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
        self.process: asyncio.subprocess.Process | None = None

    async def run(self) -> None:
        path, stream = select_motion_path(self.config.main_path, self.config.sub_path)
        self.on_status("starting", stream, None, None)
        try:
            probe = await probe_camera(
                ip=self.config.ip,
                port=self.config.port,
                username=self.config.username,
                password=self.config.password,
                rtsp_path=path,
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
                ip=self.config.ip,
                port=self.config.port,
                username=self.config.username,
                password=self.config.password,
                rtsp_path=path,
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
            analyzer = MotionFrameAnalyzer(self.config.sensitivity)
            state = MotionEventStateMachine(
                min_duration_ms=self.config.min_duration_ms,
                merge_gap_ms=self.config.merge_gap_ms,
            )
            frame_size = output_width * output_height * 3
            best_frame: np.ndarray | None = None
            best_score = -1.0
            self.on_status("running", stream, None, None)

            while True:
                try:
                    raw = await self.process.stdout.readexactly(frame_size)
                except asyncio.IncompleteReadError as exc:
                    if not exc.partial:
                        break
                    raise MotionWorkerError("motion stream ended with an incomplete frame") from exc

                timestamp = datetime.now(timezone.utc)
                frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                    (output_height, output_width, 3)
                )
                result = analyzer.analyze(frame, self.config.zones)
                zone_id = result.zone_ids[0] if result.zone_ids else None
                closed = state.update(
                    timestamp,
                    motion=result.motion,
                    score=result.score,
                    zone_id=zone_id,
                )
                for event in closed:
                    await self.on_event(event, best_frame)
                    best_frame = None
                    best_score = -1.0

                if result.motion and result.score >= best_score:
                    best_frame = frame.copy()
                    best_score = result.score
                elif not result.motion and not state.active:
                    best_frame = None
                    best_score = -1.0
                self.on_status("running", stream, timestamp, None)

            stderr = b""
            if self.process.stderr is not None:
                stderr = await self.process.stderr.read()
            message = stderr.decode(errors="replace").strip()
            raise MotionWorkerError(message[-1000:] or "motion stream ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.on_status("error", stream, None, str(exc))
            raise
        finally:
            if self.process is not None:
                await _stop_process(self.process)
                self.process = None
