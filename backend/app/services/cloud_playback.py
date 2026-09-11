import asyncio
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.system_settings import RuntimeSettings
from app.services.upload_manager import OpenListWebDAVProvider

_CLOUD_CACHE_MAX_AGE_SECONDS = 24 * 3600


class CloudPlaybackManager:
    """Restore successfully archived recordings into a temporary playback cache.

    Cloud playback is deliberately independent from UploadTask state. A failed
    playback download must never turn a successfully archived recording back into
    an upload failure.
    """

    def __init__(self) -> None:
        self.cache_dir = settings.data_dir / "cloud-playback"
        self._tasks: dict[int, asyncio.Task] = {}
        self._errors: dict[int, str] = {}
        self._semaphore = asyncio.Semaphore(2)

    def source_path(self, recording_id: int) -> Path:
        return self.cache_dir / f"{recording_id}.mp4"

    def temp_path(self, recording_id: int) -> Path:
        return self.cache_dir / f".{recording_id}.part.mp4"

    def status(self, recording_id: int) -> dict[str, Any]:
        source = self.source_path(recording_id)
        if source.exists() and source.stat().st_size > 0:
            return {"state": "ready", "error": None}
        task = self._tasks.get(recording_id)
        if task and not task.done():
            return {"state": "downloading", "error": None}
        if recording_id in self._errors:
            return {"state": "error", "error": self._errors[recording_id]}
        return {"state": "needed", "error": None}

    def mark_accessed(self, recording_id: int) -> None:
        path = self.source_path(recording_id)
        if not path.exists():
            return
        try:
            path.touch()
        except OSError:
            pass

    async def cleanup_cache(self) -> None:
        await asyncio.to_thread(self._cleanup_old_sync)

    def _cleanup_old_sync(self) -> None:
        if not self.cache_dir.exists():
            return
        cutoff = time.time() - _CLOUD_CACHE_MAX_AGE_SECONDS
        for pattern in ("*.mp4", ".*.part.mp4"):
            for path in self.cache_dir.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue

    async def start(
        self,
        recording_id: int,
        remote_path: str,
        runtime: RuntimeSettings,
    ) -> dict[str, Any]:
        state = self.status(recording_id)
        if state["state"] in {"ready", "downloading"}:
            return state

        provider = OpenListWebDAVProvider(runtime)
        if not provider.configured:
            return {"state": "error", "error": "OpenList WebDAV 未配置"}

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        await self.cleanup_cache()
        self._errors.pop(recording_id, None)
        task = asyncio.create_task(
            self._download(recording_id, remote_path, provider),
            name=f"cloud-playback-{recording_id}",
        )
        self._tasks[recording_id] = task
        return {"state": "downloading", "error": None}

    async def _download(
        self,
        recording_id: int,
        remote_path: str,
        provider: OpenListWebDAVProvider,
    ) -> None:
        async with self._semaphore:
            target = self.source_path(recording_id)
            temp = self.temp_path(recording_id)
            try:
                # The request may have waited behind another cloud restore.
                if target.exists() and target.stat().st_size > 0:
                    return
                temp.unlink(missing_ok=True)
                await provider.download(remote_path, temp)
                if not temp.exists() or temp.stat().st_size <= 0:
                    raise RuntimeError("云端录像下载结果为空")
                temp.replace(target)
                self._errors.pop(recording_id, None)
            except Exception as exc:
                temp.unlink(missing_ok=True)
                self._errors[recording_id] = str(exc)[-2000:]
            finally:
                self._tasks.pop(recording_id, None)


cloud_playback_manager = CloudPlaybackManager()
