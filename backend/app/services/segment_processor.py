import asyncio
import json
import logging
import re
import shutil
import time
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.recording import Recording
from app.services.recorder_manager import recorder_manager
from app.services.system_settings import load_runtime_settings

logger = logging.getLogger(__name__)


def safe_camera_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-.\u4e00-\u9fff]+", "_", name, flags=re.UNICODE)
    return cleaned.strip("._") or "camera"


def parse_segment_time(path: Path) -> datetime | None:
    try:
        parsed = datetime.strptime(path.stem, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None
    return parsed.astimezone()


def _fps(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


async def probe_media(path: Path) -> dict:
    command = [
        settings.ffprobe_bin,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace").strip() or "ffprobe failed")

    payload = json.loads(stdout.decode("utf-8"))
    streams = payload.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    fmt = payload.get("format") or {}
    duration = float(fmt["duration"]) if fmt.get("duration") else None

    fps_value = None
    if video:
        fps_value = _fps(video.get("avg_frame_rate")) or _fps(video.get("r_frame_rate"))

    return {
        "duration": duration,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "width": video.get("width") if video else None,
        "height": video.get("height") if video else None,
        "fps": fps_value,
        "has_video": bool(video),
        "has_audio": bool(audio),
    }


async def scan_media_packets(path: Path) -> tuple[bool, str | None]:
    """Read the complete video packet stream without decoding it.

    ffprobe only validates headers/metadata and can report a file as healthy even
    when later packets are truncated or structurally broken. A stream-copy pass
    through FFmpeg is cheap compared with full HEVC decoding, while still forcing
    the demuxer to read the whole MP4 and surface packet/container errors.
    """

    command = [
        settings.ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-xerror",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-f",
        "null",
        "-",
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    detail = stderr.decode(errors="replace").strip()
    if process.returncode != 0 or detail:
        return False, detail[-1000:] or f"packet scan exited with {process.returncode}"
    return True, None


async def decode_media_video(path: Path) -> tuple[bool, str | None]:
    """Fully decode a suspicious video segment to distinguish warning from corruption.

    This intentionally runs only after the cheap packet scan reports a problem,
    so normal recordings do not pay the CPU cost of decoding every stored frame.
    """

    command = [
        settings.ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-xerror",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-an",
        "-f",
        "null",
        "-",
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    detail = stderr.decode(errors="replace").strip()
    if process.returncode != 0 or detail:
        return False, detail[-1000:] or f"decode scan exited with {process.returncode}"
    return True, None


async def remux_to_mp4(source: Path, target: Path, video_codec: str | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.part.mp4")
    temporary.unlink(missing_ok=True)

    command = [
        settings.ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "+genpts",
        "-i",
        str(source),
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

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(stderr.decode(errors="replace").strip() or "remux failed")

    temporary.replace(target)


class SegmentProcessor:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._in_progress: set[Path] = set()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="segment-processor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except TimeoutError:
                self._task.cancel()

    def status(self) -> dict:
        return {
            "running": bool(self._task and not self._task.done()),
            "in_progress": len(self._in_progress),
            "scan_interval_seconds": settings.segment_scan_interval_seconds,
        }

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("segment scan failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=settings.segment_scan_interval_seconds
                )
            except TimeoutError:
                pass

    async def scan_once(self) -> None:
        async with SessionLocal() as session:
            runtime = await load_runtime_settings(session)
        semaphore = asyncio.Semaphore(max(1, runtime.remux_concurrency))
        tasks: list[asyncio.Task] = []
        for camera_dir in settings.staging_dir.glob("camera-*"):
            if not camera_dir.is_dir():
                continue
            try:
                camera_id = int(camera_dir.name.split("-", 1)[1])
            except (IndexError, ValueError):
                continue

            files = sorted(camera_dir.glob("*.mkv"), key=lambda path: path.stat().st_mtime)
            if not files:
                continue

            active = files[-1] if recorder_manager.is_running(camera_id) else None
            for path in files:
                if path == active or path in self._in_progress:
                    continue
                age = time.time() - path.stat().st_mtime
                if age < settings.segment_finalize_grace_seconds:
                    continue
                self._in_progress.add(path)
                tasks.append(asyncio.create_task(self._process_guarded(camera_id, path, semaphore)))

        if tasks:
            await asyncio.gather(*tasks)

    async def _process_guarded(
        self, camera_id: int, path: Path, semaphore: asyncio.Semaphore
    ) -> None:
        try:
            async with semaphore:
                await self.process_segment(camera_id, path)
        except Exception as exc:
            logger.exception("failed to process segment %s: %s", path, exc)
            failed_dir = settings.failed_dir / f"camera-{camera_id}"
            failed_dir.mkdir(parents=True, exist_ok=True)
            if path.exists():
                destination = failed_dir / path.name
                await asyncio.to_thread(shutil.move, str(path), str(destination))
        finally:
            self._in_progress.discard(path)

    async def process_segment(self, camera_id: int, source: Path) -> None:
        async with SessionLocal() as session:
            camera = await session.get(Camera, camera_id)
            if camera is None:
                raise RuntimeError(f"camera {camera_id} no longer exists")

            started_at = parse_segment_time(source) or datetime.fromtimestamp(
                source.stat().st_mtime
            ).astimezone()
            safe_name = safe_camera_name(camera.name)
            date_dir = started_at.strftime("%Y-%m-%d")
            file_name = f"{safe_name}_{started_at.strftime('%Y-%m-%d_%H-%M-%S')}.mp4"
            target = settings.recordings_dir / safe_name / date_dir / file_name

            existing = await session.scalar(select(Recording).where(Recording.mp4_path == str(target)))
            if existing and target.exists():
                source.unlink(missing_ok=True)
                return

            await remux_to_mp4(source, target, camera.video_codec)
            media = await probe_media(target)
            if not media["has_video"]:
                target.unlink(missing_ok=True)
                raise RuntimeError("final MP4 has no video stream")

            packet_ok, packet_error = await scan_media_packets(target)
            decode_ok = True
            decode_error: str | None = None
            health = "healthy"
            warning_increment = 0

            if camera.audio_codec and not media["has_audio"]:
                health = "warning"
                warning_increment += 1

            if not packet_ok:
                health = "warning"
                warning_increment += 1
                logger.warning("recording packet scan warning for %s: %s", target, packet_error)
                decode_ok, decode_error = await decode_media_video(target)
                if not decode_ok:
                    health = "unhealthy"
                    warning_increment += 1
                    logger.error(
                        "recording deep decode failed for %s: packet=%s decode=%s",
                        target,
                        packet_error,
                        decode_error,
                    )
                else:
                    logger.info(
                        "recording deep decode passed after packet warning for %s",
                        target,
                    )

            duration = media["duration"]
            ended_at = started_at + timedelta(seconds=duration) if duration else None
            recording = existing or Recording(camera_id=camera_id, mp4_path=str(target))
            recording.started_at = started_at
            recording.ended_at = ended_at
            recording.duration = duration
            recording.source_mkv_path = str(source)
            recording.file_size = target.stat().st_size
            recording.video_codec = media["video_codec"]
            recording.audio_codec = media["audio_codec"]
            recording.width = media["width"]
            recording.height = media["height"]
            recording.fps = media["fps"]
            recording.status = "ready"
            recording.health_status = health
            recording.ffprobe_ok = 1
            recording.has_video = int(media["has_video"])
            recording.has_audio = int(media["has_audio"])
            if warning_increment:
                recording.warning_count = int(recording.warning_count or 0) + warning_increment

            if existing is None:
                session.add(recording)
            await session.commit()
            source.unlink(missing_ok=True)


segment_processor = SegmentProcessor()
