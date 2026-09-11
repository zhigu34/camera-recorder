import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services.ffmpeg_builder import CameraRuntimeConfig, build_record_command, redact_command


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
        self.last_error: str | None = None
        self.started_at: datetime | None = None
        self._log_path = settings.logs_dir / f"camera-{camera.id}.log"

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
        return {
            "camera_id": self.camera.id,
            "state": self.state,
            "pid": self.process.pid if self.process and self.process.returncode is None else None,
            "restart_count": self.restart_count,
            "warning_count": self.warning_count,
            "timestamp_warning_count": self.timestamp_warning_count,
            "network_warning_count": self.network_warning_count,
            "last_error": self.last_error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
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
                command = build_record_command(self.camera, output_dir)
                await self._log(
                    f"starting ffmpeg: {' '.join(redact_command(command))}"
                )
                self.process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception as exc:  # startup failures should enter reconnect loop
                self.last_error = str(exc)
                await self._log(f"failed to start ffmpeg: {exc}")
                if self.stop_requested:
                    break
                delay = backoff[min(attempt, len(backoff) - 1)]
                attempt += 1
                self.restart_count += 1
                await asyncio.sleep(delay)
                continue

            self.state = "RECORDING"
            self.started_at = datetime.now(timezone.utc)
            stderr_task = asyncio.create_task(self._consume_stderr(self.process))
            return_code = await self.process.wait()
            await stderr_task
            self.process = None

            if self.stop_requested:
                break

            self.last_error = f"ffmpeg exited with code {return_code}"
            self.restart_count += 1
            self.state = "RECONNECTING"
            await self._log(self.last_error)
            delay = backoff[min(attempt, len(backoff) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

        self.state = "STOPPED"

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
        await asyncio.to_thread(self._append_log, self._log_path, line)

    @staticmethod
    def _append_log(path: Path, line: str) -> None:
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
