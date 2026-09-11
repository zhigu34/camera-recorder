import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.recording import Recording
from app.services.event_log import add_event
from app.services.system_settings import load_runtime_settings

_CHECK_INTERVAL_SECONDS = 60.0
_AUDIT_COOLDOWN_SECONDS = 3600.0


class StorageCleanupManager:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._last_audit_at: dict[str, datetime] = {}
        self._status: dict[str, Any] = {
            "running": False,
            "last_run_at": None,
            "last_result": None,
            "deleted_files": 0,
            "freed_bytes": 0,
            "before_percent": None,
            "after_percent": None,
            "last_error": None,
        }

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="storage-cleanup")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except TimeoutError:
                task.cancel()
        self._task = None

    def status(self) -> dict[str, Any]:
        return dict(self._status)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._status["last_error"] = str(exc)[-1000:]
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_CHECK_INTERVAL_SECONDS)
            except TimeoutError:
                pass

    @staticmethod
    def _usage() -> tuple[shutil._ntuple_diskusage, float]:
        settings.recordings_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(settings.recordings_dir)
        percent = (usage.used / usage.total * 100.0) if usage.total else 0.0
        return usage, percent

    async def _audit(
        self,
        *,
        code: str,
        level: str,
        message: str,
        metadata: dict[str, Any],
        throttle: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc)
        if throttle:
            previous = self._last_audit_at.get(code)
            if previous and (now - previous).total_seconds() < _AUDIT_COOLDOWN_SECONDS:
                return
        self._last_audit_at[code] = now
        async with SessionLocal() as session:
            add_event(
                session,
                level=level,
                category="storage",
                code=code,
                message=message,
                metadata=metadata,
            )
            await session.commit()

    async def check_once(self) -> dict[str, Any]:
        if self._lock.locked():
            return self.status()

        async with self._lock:
            async with SessionLocal() as session:
                runtime = await load_runtime_settings(session)

            before_usage, before_percent = self._usage()
            if before_percent < runtime.storage_critical_percent:
                return self.status()

            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=max(0, runtime.local_retention_hours))
            self._status.update(
                {
                    "running": True,
                    "last_run_at": now.isoformat(),
                    "last_result": "running",
                    "deleted_files": 0,
                    "freed_bytes": 0,
                    "before_percent": round(before_percent, 2),
                    "after_percent": round(before_percent, 2),
                    "last_error": None,
                }
            )

            await self._audit(
                code="storage.emergency_cleanup_started",
                level="warning",
                message="磁盘达到 critical 阈值，开始紧急清理已安全归档录像",
                metadata={
                    "used_percent": round(before_percent, 2),
                    "critical_percent": runtime.storage_critical_percent,
                    "target_percent": runtime.storage_warning_percent,
                    "local_retention_hours": runtime.local_retention_hours,
                    "free_bytes": before_usage.free,
                },
                throttle=True,
            )

            deleted = 0
            freed_bytes = 0
            failures: list[str] = []

            try:
                async with SessionLocal() as session:
                    recordings = list(
                        await session.scalars(
                            select(Recording)
                            .where(
                                Recording.status == "ready",
                                Recording.upload_status == "success",
                                Recording.ended_at.is_not(None),
                                Recording.ended_at <= cutoff,
                            )
                            .order_by(Recording.ended_at.asc(), Recording.id.asc())
                            .limit(5000)
                        )
                    )

                    if not recordings:
                        self._status.update(
                            {
                                "running": False,
                                "last_result": "blocked",
                                "after_percent": round(before_percent, 2),
                            }
                        )
                        await self._audit(
                            code="storage.emergency_cleanup_blocked",
                            level="error",
                            message="磁盘空间 critical，但没有满足保留策略且已上传成功的安全清理候选",
                            metadata={
                                "used_percent": round(before_percent, 2),
                                "critical_percent": runtime.storage_critical_percent,
                                "local_retention_hours": runtime.local_retention_hours,
                            },
                            throttle=True,
                        )
                        return self.status()

                    for recording in recordings:
                        _, current_percent = self._usage()
                        if current_percent <= runtime.storage_warning_percent:
                            break

                        path = Path(recording.mp4_path)
                        file_size = int(recording.file_size or 0)
                        if path.exists():
                            try:
                                if not file_size:
                                    file_size = path.stat().st_size
                                await asyncio.to_thread(path.unlink)
                            except OSError as exc:
                                failures.append(f"{recording.id}:{exc}")
                                continue

                        recording.status = "deleted"
                        deleted += 1
                        freed_bytes += max(0, file_size)

                    if deleted:
                        await session.commit()

                _, after_percent = self._usage()
                result = "completed" if deleted else "blocked"
                self._status.update(
                    {
                        "running": False,
                        "last_result": result,
                        "deleted_files": deleted,
                        "freed_bytes": freed_bytes,
                        "after_percent": round(after_percent, 2),
                        "last_error": "; ".join(failures[-5:]) if failures else None,
                    }
                )

                await self._audit(
                    code=(
                        "storage.emergency_cleanup_completed"
                        if deleted
                        else "storage.emergency_cleanup_blocked"
                    ),
                    level="info" if deleted else "error",
                    message=(
                        f"紧急磁盘清理完成：删除 {deleted} 个已归档录像，释放约 {freed_bytes} 字节"
                        if deleted
                        else "磁盘空间仍处于 critical，安全候选未能释放空间"
                    ),
                    metadata={
                        "deleted_files": deleted,
                        "freed_bytes": freed_bytes,
                        "before_percent": round(before_percent, 2),
                        "after_percent": round(after_percent, 2),
                        "target_percent": runtime.storage_warning_percent,
                        "failure_count": len(failures),
                    },
                    throttle=not bool(deleted),
                )
                return self.status()
            except Exception as exc:
                self._status.update(
                    {
                        "running": False,
                        "last_result": "failed",
                        "last_error": str(exc)[-1000:],
                    }
                )
                await self._audit(
                    code="storage.emergency_cleanup_failed",
                    level="error",
                    message="紧急磁盘清理执行失败",
                    metadata={
                        "error": str(exc)[-1000:],
                        "before_percent": round(before_percent, 2),
                    },
                    throttle=True,
                )
                return self.status()


storage_cleanup_manager = StorageCleanupManager()
