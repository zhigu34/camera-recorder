import asyncio
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.email_notifier import email_notifier
from app.services.event_log import add_event
from app.services.ffmpeg_builder import CameraRuntimeConfig, build_record_command, redact_command
from app.services.system_settings import load_runtime_settings


_TIMESTAMP_MARKERS = (
    "non-monotonic dts",
    "timestamps are unset",
    "starting new cluster due to timestamp",
)
_NETWORK_MARKERS = (
    "connection timed out",
    "connection reset",
    "connection refused",
    "could not find codec parameters",
    "server returned",
    "rtsp error",
    "invalid data found",
)
_STABLE_CONNECTION_SECONDS = 60.0
_CONSECUTIVE_FAILURE_THRESHOLD = 3
CAMERA_LOG_MAX_BYTES = 20 * 1024 * 1024
CAMERA_LOG_BACKUPS = 5


class CameraWorker:
    def __init__(self, camera: CameraRuntimeConfig):
        self.camera = camera
        self.state = "STOPPED"
        self.process: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task | None = None
        self.stop_requested = False
        self.restart_count = 0
        self.warning_count = 0
        self.timestamp_warning_count = 0
        self.network_warning_count = 0
        self.consecutive_failure_count = 0
        self.failure_streak_alert_active = False
        self.last_failure_at: datetime | None = None
        self.last_error: str | None = None
        self.started_at: datetime | None = None
        self.offline_since: datetime | None = None
        self.offline_alert_active = False
        self._outage_restart_base = 0
        self._offline_alert_task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None
        self._stability_task: asyncio.Task | None = None
        self._log_path = settings.logs_dir / f"camera-{camera.id}.log"
        self._log_lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done() and not self.stop_requested

    async def start(self) -> None:
        if self.running:
            return
        self.stop_requested = False
        self.task = asyncio.create_task(self._run_loop(), name=f"camera-worker-{self.camera.id}")

    async def stop(self) -> None:
        self.stop_requested = True
        self.state = "STOPPING"
        self._cancel_connectivity_tasks()
        self._cancel_stability_task()
        self.offline_since = None
        self.offline_alert_active = False

        process = self.process
        if process and process.returncode is None:
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=15)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.kill()
                    await process.wait()

        if self.task and not self.task.done():
            try:
                await asyncio.wait_for(self.task, timeout=5)
            except TimeoutError:
                self.task.cancel()
        self.process = None
        self.state = "STOPPED"

    def snapshot(self) -> dict:
        now = datetime.now(timezone.utc)
        effective_failures = self.consecutive_failure_count
        if (
            self.state == "RECORDING"
            and self.started_at is not None
            and (now - self.started_at).total_seconds() >= _STABLE_CONNECTION_SECONDS
        ):
            effective_failures = 0

        current_offline_seconds = 0
        current_outage_restarts = 0
        if self.offline_since is not None:
            current_offline_seconds = max(0, int((now - self.offline_since).total_seconds()))
            current_outage_restarts = max(0, self.restart_count - self._outage_restart_base)

        return {
            "camera_id": self.camera.id,
            "state": self.state,
            "pid": self.process.pid if self.process and self.process.returncode is None else None,
            "restart_count": self.restart_count,
            "warning_count": self.warning_count,
            "timestamp_warning_count": self.timestamp_warning_count,
            "network_warning_count": self.network_warning_count,
            "consecutive_failure_count": effective_failures,
            "continuous_failure_active": effective_failures >= _CONSECUTIVE_FAILURE_THRESHOLD,
            "last_failure_at": self.last_failure_at.isoformat() if self.last_failure_at else None,
            "last_error": self.last_error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "offline_since": self.offline_since.isoformat() if self.offline_since else None,
            "current_offline_seconds": current_offline_seconds,
            "current_outage_restarts": current_outage_restarts,
            "offline_alert_active": self.offline_alert_active,
        }

    async def _run_loop(self) -> None:
        backoff = [3, 5, 10, 20, 30, 60]
        attempt = 0
        output_dir = settings.staging_dir / f"camera-{self.camera.id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        while not self.stop_requested:
            self.state = "STARTING" if attempt == 0 else "RECONNECTING"
            try:
                async with SessionLocal() as session:
                    runtime = await load_runtime_settings(session)
                command = build_record_command(self.camera, output_dir, runtime)
                await self._log(f"starting ffmpeg: {' '.join(redact_command(command))}")
                self.process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception as exc:
                self.last_error = str(exc)
                self.restart_count += 1
                self.consecutive_failure_count += 1
                self.last_failure_at = datetime.now(timezone.utc)
                await self._log(f"failed to start ffmpeg: {exc}")
                await self._record_camera_event(
                    level="error",
                    code="camera.ffmpeg_start_failed",
                    message=f"摄像头 {self.camera.name} FFmpeg 启动失败",
                    metadata={
                        "reason": self.last_error[-1000:],
                        "restart_count": self.restart_count,
                        "consecutive_failures": self.consecutive_failure_count,
                    },
                )
                await self._mark_disconnected(self.last_error)
                await self._check_failure_streak()
                if self.stop_requested:
                    break
                delay = backoff[min(attempt, len(backoff) - 1)]
                attempt += 1
                await asyncio.sleep(delay)
                continue

            self.state = "RECORDING"
            self.started_at = datetime.now(timezone.utc)
            process_started = time.monotonic()
            self._start_recovery_confirmation(self.process)
            self._start_stability_confirmation(self.process)
            stderr_task = asyncio.create_task(self._consume_stderr(self.process))
            return_code = await self.process.wait()
            runtime_seconds = time.monotonic() - process_started
            await stderr_task
            self._cancel_recovery_task()
            self._cancel_stability_task()
            self.process = None

            if self.stop_requested:
                break

            if runtime_seconds >= _STABLE_CONNECTION_SECONDS:
                attempt = 0
                self.consecutive_failure_count = 0
                self.failure_streak_alert_active = False

            self.last_error = f"ffmpeg exited with code {return_code} after {runtime_seconds:.1f}s"
            self.restart_count += 1
            self.consecutive_failure_count += 1
            self.last_failure_at = datetime.now(timezone.utc)
            self.state = "RECONNECTING"
            await self._log(self.last_error)
            await self._record_camera_event(
                level="error",
                code="camera.ffmpeg_exited",
                message=f"摄像头 {self.camera.name} FFmpeg 异常退出",
                metadata={
                    "return_code": return_code,
                    "runtime_seconds": round(runtime_seconds, 3),
                    "restart_count": self.restart_count,
                    "consecutive_failures": self.consecutive_failure_count,
                },
            )
            await self._mark_disconnected(self.last_error)
            await self._check_failure_streak()
            delay = backoff[min(attempt, len(backoff) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

        self._cancel_connectivity_tasks()
        self._cancel_stability_task()
        self.state = "STOPPED"

    async def _check_failure_streak(self) -> None:
        if (
            self.consecutive_failure_count < _CONSECUTIVE_FAILURE_THRESHOLD
            or self.failure_streak_alert_active
        ):
            return
        self.failure_streak_alert_active = True
        await self._record_camera_event(
            level="error",
            code="camera.ffmpeg_failure_streak",
            message=(
                f"摄像头 {self.camera.name} FFmpeg 连续失败 "
                f"{self.consecutive_failure_count} 次"
            ),
            metadata={
                "consecutive_failures": self.consecutive_failure_count,
                "restart_count": self.restart_count,
                "threshold": _CONSECUTIVE_FAILURE_THRESHOLD,
                "last_error": self.last_error[-1000:] if self.last_error else None,
            },
        )

    def _start_stability_confirmation(self, process: asyncio.subprocess.Process) -> None:
        self._cancel_stability_task()
        self._stability_task = asyncio.create_task(
            self._confirm_stable_process(process),
            name=f"camera-stable-{self.camera.id}",
        )

    async def _confirm_stable_process(self, process: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.sleep(_STABLE_CONNECTION_SECONDS)
            if (
                self.stop_requested
                or self.process is not process
                or process.returncode is not None
            ):
                return
            had_streak = self.failure_streak_alert_active
            previous_failures = self.consecutive_failure_count
            self.consecutive_failure_count = 0
            self.failure_streak_alert_active = False
            if had_streak:
                await self._record_camera_event(
                    level="info",
                    code="camera.ffmpeg_stable",
                    message=f"摄像头 {self.camera.name} FFmpeg 已稳定运行 60 秒",
                    metadata={"previous_consecutive_failures": previous_failures},
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._log(f"stability confirmation error: {exc}")

    async def _mark_disconnected(self, reason: str) -> None:
        if self.stop_requested:
            return
        if self.offline_since is None:
            self.offline_since = datetime.now(timezone.utc)
            self._outage_restart_base = max(0, self.restart_count - 1)
            await self._log(f"camera connectivity lost: {reason}")
            await self._record_camera_event(
                level="warning",
                code="camera.connection_lost",
                message=f"摄像头 {self.camera.name} 录像连接中断",
                metadata={
                    "offline_since": self.offline_since.isoformat(),
                    "reason": reason[-1000:],
                    "restart_count": self.restart_count,
                },
            )
        if self._offline_alert_task is None or self._offline_alert_task.done():
            self._offline_alert_task = asyncio.create_task(
                self._offline_alert_after_delay(),
                name=f"camera-offline-alert-{self.camera.id}",
            )

    async def _offline_alert_after_delay(self) -> None:
        try:
            config = await email_notifier.load_config()
            await asyncio.sleep(max(0.0, config.offline_alert_seconds))
            if self.stop_requested or self.offline_since is None or self.offline_alert_active:
                return

            config = await email_notifier.load_config()
            self.offline_alert_active = True
            offline_since = self.offline_since
            await self._record_camera_event(
                level="error",
                code="camera.offline",
                message=(
                    f"摄像头 {self.camera.name} 持续掉线超过 "
                    f"{int(config.offline_alert_seconds)} 秒"
                ),
            )
            if config.email_enabled:
                await email_notifier.send_offline(
                    camera_id=self.camera.id,
                    camera_name=self.camera.name,
                    camera_ip=self.camera.ip,
                    rtsp_path=self.camera.rtsp_path,
                    offline_since=offline_since,
                    last_error=self.last_error,
                    restart_count=self.restart_count,
                    config=config,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._log(f"offline notification error: {exc}")

    def _start_recovery_confirmation(self, process: asyncio.subprocess.Process) -> None:
        self._cancel_recovery_task()
        if self.offline_since is None:
            return
        self._recovery_task = asyncio.create_task(
            self._confirm_recovery(process),
            name=f"camera-recovery-confirm-{self.camera.id}",
        )

    async def _confirm_recovery(self, process: asyncio.subprocess.Process) -> None:
        try:
            config = await email_notifier.load_config()
            await asyncio.sleep(max(0.0, config.recovery_stable_seconds))
            if (
                self.stop_requested
                or self.process is not process
                or process.returncode is not None
                or self.offline_since is None
            ):
                return

            offline_since = self.offline_since
            recovered_at = datetime.now(timezone.utc)
            outage_seconds = max(0.0, (recovered_at - offline_since).total_seconds())
            outage_restarts = max(0, self.restart_count - self._outage_restart_base)
            had_alert = self.offline_alert_active
            self.offline_since = None
            self.offline_alert_active = False
            self._outage_restart_base = self.restart_count
            self._cancel_offline_alert_task()
            self.last_error = None

            await self._record_camera_event(
                level="info",
                code="camera.connection_restored",
                message=(
                    f"摄像头 {self.camera.name} 录像连接恢复，"
                    f"本次中断 {outage_seconds:.1f} 秒"
                ),
                metadata={
                    "offline_since": offline_since.isoformat(),
                    "recovered_at": recovered_at.isoformat(),
                    "duration_seconds": round(outage_seconds, 3),
                    "outage_restarts": outage_restarts,
                },
            )

            if had_alert:
                await self._record_camera_event(
                    level="info",
                    code="camera.recovered",
                    message=f"摄像头 {self.camera.name} 录像连接已恢复",
                )
                config = await email_notifier.load_config()
                if config.email_enabled and config.notify_recovery:
                    await email_notifier.send_recovery(
                        camera_id=self.camera.id,
                        camera_name=self.camera.name,
                        camera_ip=self.camera.ip,
                        rtsp_path=self.camera.rtsp_path,
                        offline_since=offline_since,
                        config=config,
                    )
            await self._log("camera connectivity stable")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._log(f"recovery notification error: {exc}")

    async def _record_camera_event(
        self,
        *,
        level: str,
        code: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            async with SessionLocal() as session:
                add_event(
                    session,
                    level=level,
                    category="camera",
                    code=code,
                    message=message,
                    camera_id=self.camera.id,
                    metadata=metadata,
                )
                await session.commit()
        except Exception as exc:
            await self._log(f"failed to persist camera event: {exc}")

    def _cancel_connectivity_tasks(self) -> None:
        self._cancel_offline_alert_task()
        self._cancel_recovery_task()

    def _cancel_offline_alert_task(self) -> None:
        task = self._offline_alert_task
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._offline_alert_task = None

    def _cancel_recovery_task(self) -> None:
        task = self._recovery_task
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._recovery_task = None

    def _cancel_stability_task(self) -> None:
        task = self._stability_task
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._stability_task = None

    async def _consume_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return
        while True:
            raw = await process.stderr.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue
            lower = line.lower()
            self.warning_count += 1
            if any(marker in lower for marker in _TIMESTAMP_MARKERS):
                self.timestamp_warning_count += 1
            if any(marker in lower for marker in _NETWORK_MARKERS):
                self.network_warning_count += 1
            if "error" in lower or "failed" in lower or "timeout" in lower:
                self.last_error = line[-1000:]
            await self._log(line)

    async def _log(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"{timestamp} {message}\n"
        async with self._log_lock:
            await asyncio.to_thread(self._append_log, self._log_path, line)

    @staticmethod
    def _append_log(path: Path, line: str) -> None:
        encoded_size = len(line.encode("utf-8"))
        if (
            path.exists()
            and path.stat().st_size > 0
            and path.stat().st_size + encoded_size > CAMERA_LOG_MAX_BYTES
        ):
            for index in range(CAMERA_LOG_BACKUPS, 1, -1):
                source = path.with_name(f"{path.name}.{index - 1}")
                target = path.with_name(f"{path.name}.{index}")
                if source.exists():
                    source.replace(target)
            if CAMERA_LOG_BACKUPS > 0:
                path.replace(path.with_name(f"{path.name}.1"))
            else:
                path.unlink(missing_ok=True)

        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


class RecorderManager:
    def __init__(self) -> None:
        self.workers: dict[int, CameraWorker] = {}
        self._lock = asyncio.Lock()

    async def start(self, camera: CameraRuntimeConfig) -> dict:
        async with self._lock:
            existing = self.workers.get(camera.id)
            if existing and existing.running:
                return existing.snapshot()
            worker = CameraWorker(camera)
            self.workers[camera.id] = worker
            await worker.start()
            return worker.snapshot()

    async def restart(self, camera: CameraRuntimeConfig) -> dict:
        await self.stop(camera.id)
        return await self.start(camera)

    async def stop(self, camera_id: int) -> dict:
        async with self._lock:
            worker = self.workers.get(camera_id)
            if not worker:
                return {"camera_id": camera_id, "state": "STOPPED", "pid": None}
            await worker.stop()
            return worker.snapshot()

    async def stop_all(self) -> None:
        for camera_id in list(self.workers):
            await self.stop(camera_id)

    def is_running(self, camera_id: int) -> bool:
        worker = self.workers.get(camera_id)
        return bool(worker and worker.running)

    def status(self, camera_id: int | None = None) -> dict | list[dict]:
        if camera_id is not None:
            worker = self.workers.get(camera_id)
            if not worker:
                return {"camera_id": camera_id, "state": "STOPPED", "pid": None}
            return worker.snapshot()
        return [worker.snapshot() for worker in self.workers.values()]


recorder_manager = RecorderManager()
