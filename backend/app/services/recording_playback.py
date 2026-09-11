import asyncio
import time
from pathlib import Path
from typing import Any

from app.core.config import settings

_PROXY_CACHE_MAX_AGE_SECONDS = 24 * 3600


class RecordingPlaybackManager:
    def __init__(self) -> None:
        self.proxy_dir = settings.data_dir / "playback-proxies"
        self._tasks: dict[int, asyncio.Task] = {}
        self._errors: dict[int, str] = {}
        self._semaphore = asyncio.Semaphore(1)

    def proxy_path(self, recording_id: int) -> Path:
        return self.proxy_dir / f"{recording_id}.mp4"

    @staticmethod
    def can_direct_play(video_codec: str | None) -> bool:
        return (video_codec or "").lower() in {"h264", "avc", "avc1"}

    def status(self, recording_id: int, video_codec: str | None) -> dict[str, Any]:
        if self.can_direct_play(video_codec):
            return {"state": "direct", "direct": True, "error": None}
        proxy = self.proxy_path(recording_id)
        if proxy.exists() and proxy.stat().st_size > 0:
            return {"state": "ready", "direct": False, "error": None}
        task = self._tasks.get(recording_id)
        if task and not task.done():
            return {"state": "generating", "direct": False, "error": None}
        if recording_id in self._errors:
            return {"state": "error", "direct": False, "error": self._errors[recording_id]}
        return {"state": "needed", "direct": False, "error": None}

    async def cleanup_cache(self) -> None:
        await asyncio.to_thread(self._cleanup_old_sync)

    def mark_accessed(self, recording_id: int) -> None:
        proxy = self.proxy_path(recording_id)
        if not proxy.exists():
            return
        try:
            proxy.touch()
        except OSError:
            pass

    async def start(self, recording_id: int, source: Path, video_codec: str | None) -> dict[str, Any]:
        state = self.status(recording_id, video_codec)
        if state["state"] == "direct":
            if not source.exists():
                raise FileNotFoundError(str(source))
            return state
        if state["state"] in {"ready", "generating"}:
            return state
        if not source.exists():
            raise FileNotFoundError(str(source))
        self.proxy_dir.mkdir(parents=True, exist_ok=True)
        await self.cleanup_cache()
        self._errors.pop(recording_id, None)
        task = asyncio.create_task(
            self._generate(recording_id, source),
            name=f"playback-proxy-{recording_id}",
        )
        self._tasks[recording_id] = task
        return {"state": "generating", "direct": False, "error": None}

    def _cleanup_old_sync(self) -> None:
        if not self.proxy_dir.exists():
            return
        cutoff = time.time() - _PROXY_CACHE_MAX_AGE_SECONDS
        for pattern in ("*.mp4", "*.part.mp4"):
            for path in self.proxy_dir.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue

    async def _generate(self, recording_id: int, source: Path) -> None:
        async with self._semaphore:
            target = self.proxy_path(recording_id)
            temp = target.with_suffix(".part.mp4")
            try:
                temp.unlink(missing_ok=True)
                command = [
                    settings.ffmpeg_bin,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-vf",
                    "scale='min(1280,iw)':-2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "25",
                    "-threads",
                    "2",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "96k",
                    "-movflags",
                    "+faststart",
                    str(temp),
                ]
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await process.communicate()
                if process.returncode != 0:
                    detail = stderr.decode(errors="replace")[-2000:].strip()
                    raise RuntimeError(detail or f"ffmpeg exited with code {process.returncode}")
                if not temp.exists() or temp.stat().st_size <= 0:
                    raise RuntimeError("playback proxy was not created")
                temp.replace(target)
                self._errors.pop(recording_id, None)
            except Exception as exc:
                temp.unlink(missing_ok=True)
                self._errors[recording_id] = str(exc)[-2000:]
            finally:
                self._tasks.pop(recording_id, None)


recording_playback_manager = RecordingPlaybackManager()
