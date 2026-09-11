import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.health_sample import CameraHealthSample
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule import recording_schedule_allows
from app.services.system_settings import load_runtime_settings

_SAMPLE_INTERVAL_SECONDS = 60.0
_RETENTION_DAYS = 7


def _as_int(value) -> int:
    return int(value or 0)


class HealthSampler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_cleanup_at: datetime | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        await self.sample_once()
        self._task = asyncio.create_task(self._run(), name="health-sampler")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except TimeoutError:
                task.cancel()
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_SAMPLE_INTERVAL_SECONDS)
                break
            except TimeoutError:
                pass

            try:
                await self.sample_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Sampling must never affect recording, remux or upload workers.
                continue

    async def sample_once(self) -> int:
        now = datetime.now(timezone.utc)
        local_now = now.astimezone()
        runtime_rows = recorder_manager.status()
        runtime_by_camera = {
            int(item["camera_id"]): item
            for item in runtime_rows
            if isinstance(item, dict) and item.get("camera_id") is not None
        }

        async with SessionLocal() as session:
            runtime_settings = await load_runtime_settings(session)
            cameras = list(
                await session.scalars(
                    select(Camera).where(Camera.enabled.is_(True)).order_by(Camera.id)
                )
            )

            for camera in cameras:
                runtime = runtime_by_camera.get(camera.id, {})
                state = str(runtime.get("state") or "STOPPED")
                expected = bool(
                    runtime_settings.auto_start_enabled
                    and camera.auto_record
                    and recording_schedule_allows(camera, local_now)
                )
                monitored_value = state == "RECORDING" if expected else None
                session.add(
                    CameraHealthSample(
                        camera_id=camera.id,
                        sampled_at=now,
                        state=state,
                        expected_recording=expected,
                        online=monitored_value,
                        recorder_ok=monitored_value,
                        restart_count=_as_int(runtime.get("restart_count")),
                        timestamp_warning_count=_as_int(
                            runtime.get("timestamp_warning_count")
                        ),
                        network_warning_count=_as_int(runtime.get("network_warning_count")),
                    )
                )

            if (
                self._last_cleanup_at is None
                or now - self._last_cleanup_at >= timedelta(hours=1)
            ):
                cutoff = now - timedelta(days=_RETENTION_DAYS)
                await session.execute(
                    delete(CameraHealthSample).where(CameraHealthSample.sampled_at < cutoff)
                )
                self._last_cleanup_at = now

            await session.commit()
        return len(cameras)


health_sampler = HealthSampler()
