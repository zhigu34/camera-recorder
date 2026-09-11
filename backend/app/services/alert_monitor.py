import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.event import Event
from app.models.upload import UploadTask
from app.services.alert_dispatcher import alert_dispatcher
from app.services.storage_manager import storage_snapshot
from app.services.system_settings import load_runtime_settings

_POLL_INTERVAL_SECONDS = 30.0
_INTERESTING_CODES = {
    "camera.ffmpeg_failure_streak",
    "camera.ffmpeg_stable",
    "storage.emergency_cleanup_blocked",
    "storage.emergency_cleanup_failed",
    "storage.emergency_cleanup_completed",
}


class AlertMonitor:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_event_id = 0
        self._status: dict[str, Any] = {
            "running": False,
            "last_check_at": None,
            "last_error": None,
            "last_event_id": 0,
        }

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        async with SessionLocal() as session:
            latest = await session.scalar(select(func.max(Event.id)))
        self._last_event_id = int(latest or 0)
        self._status.update({"running": True, "last_event_id": self._last_event_id})
        self._task = asyncio.create_task(self._run(), name="alert-monitor")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except TimeoutError:
                task.cancel()
        self._task = None
        self._status["running"] = False

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
                await asyncio.wait_for(self._stop.wait(), timeout=_POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass

    async def check_once(self) -> None:
        await self._process_events()
        await self._check_storage()
        await self._check_uploads()
        self._status.update(
            {
                "last_check_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
                "last_event_id": self._last_event_id,
            }
        )

    @staticmethod
    def _metadata(event: Event) -> dict[str, Any]:
        if not event.metadata_json:
            return {}
        try:
            value = json.loads(event.metadata_json)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    async def _process_events(self) -> None:
        async with SessionLocal() as session:
            events = list(
                await session.scalars(
                    select(Event)
                    .where(
                        Event.id > self._last_event_id,
                        Event.code.in_(_INTERESTING_CODES),
                    )
                    .order_by(Event.id)
                    .limit(500)
                )
            )

            camera_ids = {event.camera_id for event in events if event.camera_id is not None}
            cameras: dict[int, Camera] = {}
            if camera_ids:
                rows = list(
                    await session.scalars(select(Camera).where(Camera.id.in_(camera_ids)))
                )
                cameras = {camera.id: camera for camera in rows}

        for event in events:
            self._last_event_id = max(self._last_event_id, event.id)
            metadata = self._metadata(event)

            if event.code == "camera.ffmpeg_failure_streak" and event.camera_id is not None:
                camera = cameras.get(event.camera_id)
                name = camera.name if camera else f"#{event.camera_id}"
                ip = camera.ip if camera else "-"
                failures = int(metadata.get("consecutive_failures") or 0)
                await alert_dispatcher.alert(
                    key=f"camera:{event.camera_id}:ffmpeg_failure_streak",
                    subject=f"[Camera Recorder] FFmpeg 连续失败：{name}",
                    body=(
                        "录像进程发生连续失败，系统仍会继续自动重连。\n\n"
                        f"摄像头：{name}\n"
                        f"IP：{ip}\n"
                        f"连续失败：{failures} 次\n"
                        f"累计重启：{int(metadata.get('restart_count') or 0)} 次\n"
                        f"最近错误：{metadata.get('last_error') or '-'}\n"
                    ),
                    camera_id=event.camera_id,
                    success_code="notification.ffmpeg_failure_streak_email_sent",
                )
                continue

            if event.code == "camera.ffmpeg_stable" and event.camera_id is not None:
                # Camera offline/recovery already has its own recovery email. Clear the
                # streak incident silently to avoid sending duplicate recovery emails.
                await alert_dispatcher.clear(
                    f"camera:{event.camera_id}:ffmpeg_failure_streak"
                )
                continue

            if event.code in {
                "storage.emergency_cleanup_blocked",
                "storage.emergency_cleanup_failed",
            }:
                reason = (
                    "没有满足安全条件的可删除录像"
                    if event.code.endswith("blocked")
                    else metadata.get("error") or "紧急清理执行失败"
                )
                await alert_dispatcher.alert(
                    key="storage:cleanup_issue",
                    subject="[Camera Recorder] 磁盘紧急清理受阻",
                    body=(
                        f"{event.message}\n\n"
                        f"原因：{reason}\n"
                        "系统不会删除未上传成功、正在上传或仍在保留期内的录像。\n"
                        "请尽快检查磁盘容量、上传状态和本地保留策略。\n"
                    ),
                    success_code="notification.storage_cleanup_issue_email_sent",
                )
                continue

            if event.code == "storage.emergency_cleanup_completed":
                await alert_dispatcher.clear("storage:cleanup_issue")

    async def _check_storage(self) -> None:
        snapshot = await storage_snapshot()
        used_percent = float(snapshot["used_percent"])
        warning_percent = float(snapshot["warning_percent"])
        critical_percent = float(snapshot["critical_percent"])

        if snapshot["state"] == "critical":
            await alert_dispatcher.alert(
                key="storage:critical",
                subject="[Camera Recorder] 磁盘空间严重不足",
                body=(
                    "录像磁盘已经达到 critical 阈值。\n\n"
                    f"当前占用：{used_percent:.2f}%\n"
                    f"warning 阈值：{warning_percent:.2f}%\n"
                    f"critical 阈值：{critical_percent:.2f}%\n"
                    f"剩余空间：{int(snapshot['free_bytes'])} 字节\n\n"
                    "系统会尝试清理已上传成功且超过本地保留期的录像；"
                    "不会删除待上传、上传失败或仍在保留期内的文件。\n"
                ),
                success_code="notification.storage_critical_email_sent",
            )
            return

        if used_percent <= warning_percent:
            recovered = await alert_dispatcher.recover(
                key="storage:critical",
                subject="[Camera Recorder] 磁盘空间已恢复",
                body=(
                    "录像磁盘已经恢复到 warning 阈值以内。\n\n"
                    f"当前占用：{used_percent:.2f}%\n"
                    f"warning 阈值：{warning_percent:.2f}%\n"
                    f"剩余空间：{int(snapshot['free_bytes'])} 字节\n"
                ),
                success_code="notification.storage_recovery_email_sent",
            )
            if recovered or snapshot["state"] == "healthy":
                await alert_dispatcher.clear("storage:cleanup_issue")

    async def _check_uploads(self) -> None:
        async with SessionLocal() as session:
            runtime = await load_runtime_settings(session)
            if not runtime.upload_enabled:
                await alert_dispatcher.clear("upload:failed")
                return

            failed_count = int(
                await session.scalar(
                    select(func.count(UploadTask.id)).where(UploadTask.status == "failed")
                )
                or 0
            )
            latest_failed = await session.scalar(
                select(UploadTask)
                .where(UploadTask.status == "failed")
                .order_by(UploadTask.updated_at.desc(), UploadTask.id.desc())
                .limit(1)
            )

        if failed_count > 0 and latest_failed is not None:
            await alert_dispatcher.alert(
                key="upload:failed",
                subject="[Camera Recorder] 云端上传持续失败",
                body=(
                    "上传任务已经耗尽自动重试或进入不可继续处理的失败状态。\n\n"
                    f"当前 failed 任务：{failed_count} 个\n"
                    f"最近任务 ID：{latest_failed.id}\n"
                    f"远端路径：{latest_failed.remote_path}\n"
                    f"重试次数：{latest_failed.retry_count}\n"
                    f"最近错误：{latest_failed.last_error or '-'}\n\n"
                    "本地录像不会因为上传失败而删除。请检查 OpenList/115、网络和 WebDAV 配置。\n"
                ),
                success_code="notification.upload_failure_email_sent",
            )
            return

        await alert_dispatcher.recover(
            key="upload:failed",
            subject="[Camera Recorder] 云端上传故障已恢复",
            body="当前已经没有处于 failed 状态的上传任务，上传队列已恢复到可继续处理状态。\n",
            success_code="notification.upload_recovery_email_sent",
        )


alert_monitor = AlertMonitor()
