from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.services.camera_config import runtime_config
from app.services.event_log import add_event
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule import recording_schedule_allows, schedule_label
from app.services.system_settings import load_runtime_settings

_POLL_INTERVAL_SECONDS = 10.0


class RecordingScheduleManager:
    """Start/stop auto-record cameras according to their local weekly windows.

    Only recorders started by this manager are automatically stopped at a window
    boundary. Manual starts are treated as explicit overrides. Manual stops pause
    the current automatic window and are released after the camera leaves that
    window, so the next window can start normally.

    This manager owns schedule state only. It must never write camera connectivity
    state; Probe owns that independently and RecorderManager owns recorder state.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._managed: set[int] = set()
        self._manual_running: set[int] = set()
        self._manual_paused: set[int] = set()
        self._camera_status: dict[int, dict[str, Any]] = {}
        self._last_check_at: str | None = None
        self._last_error: str | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        await self.reconcile()
        self._task = asyncio.create_task(self._run(), name="recording-schedule-manager")

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
                await asyncio.wait_for(self._stop.wait(), timeout=_POLL_INTERVAL_SECONDS)
                break
            except TimeoutError:
                pass
            try:
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)[-1000:]

    def note_manual_start(self, camera_id: int) -> None:
        self._managed.discard(camera_id)
        self._manual_paused.discard(camera_id)
        self._manual_running.add(camera_id)
        snapshot = self._camera_status.get(camera_id)
        if snapshot is not None:
            snapshot.update({"mode": "manual", "schedule_state": "manual_override"})

    def note_manual_stop(self, camera_id: int) -> None:
        self._managed.discard(camera_id)
        self._manual_running.discard(camera_id)
        self._manual_paused.add(camera_id)
        snapshot = self._camera_status.get(camera_id)
        if snapshot is not None:
            snapshot.update({"mode": "manual_paused", "schedule_state": "manual_paused"})

    def clear_override(self, camera_id: int) -> None:
        self._managed.discard(camera_id)
        self._manual_running.discard(camera_id)
        self._manual_paused.discard(camera_id)

    def reset_for_schedule_change(self, camera_id: int) -> None:
        """Return a camera to schedule ownership after an explicit plan edit."""

        self._manual_running.discard(camera_id)
        self._manual_paused.discard(camera_id)
        self._camera_status.pop(camera_id, None)
        if recorder_manager.is_running(camera_id):
            self._managed.add(camera_id)

    def forget(self, camera_id: int) -> None:
        self.clear_override(camera_id)
        self._camera_status.pop(camera_id, None)

    def state_for(self, camera: Camera) -> str:
        """Return schedule state without mixing in connectivity or recorder state."""

        # Manual actions must be visible immediately instead of waiting for the
        # next periodic reconcile to refresh the cached schedule snapshot.
        if camera.id in self._manual_running:
            return "manual_override"
        if camera.id in self._manual_paused:
            return "manual_paused"
        snapshot = self._camera_status.get(camera.id)
        if snapshot and snapshot.get("schedule_state"):
            return str(snapshot["schedule_state"])
        if not camera.enabled or not camera.auto_record:
            return "disabled"
        if camera.recording_schedule_enabled:
            in_window = recording_schedule_allows(camera, datetime.now().astimezone())
            return "in_window" if in_window else "scheduled"
        return "automatic"

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._task and not self._task.done()),
            "poll_interval_seconds": _POLL_INTERVAL_SECONDS,
            "last_check_at": self._last_check_at,
            "last_error": self._last_error,
            "managed_camera_ids": sorted(self._managed),
            "manual_running_camera_ids": sorted(self._manual_running),
            "manual_paused_camera_ids": sorted(self._manual_paused),
            "cameras": list(self._camera_status.values()),
        }

    async def reconcile(self) -> None:
        """Reconcile every camera without letting one bad camera break the whole pass.

        Schedule edits call this method synchronously after their database commit.
        A runtime failure on an unrelated camera must therefore be represented as
        schedule_state=error, not propagated as an HTTP 500 for an already-saved
        configuration change. The periodic manager will retry on the next pass.
        """

        now_local = datetime.now().astimezone()
        errors: list[str] = []
        async with SessionLocal() as session:
            runtime = await load_runtime_settings(session)
            cameras = list(await session.scalars(select(Camera).order_by(Camera.id)))
            known_ids = {camera.id for camera in cameras}
            self._managed.intersection_update(known_ids)
            self._manual_running.intersection_update(known_ids)
            self._manual_paused.intersection_update(known_ids)

            for camera in cameras:
                try:
                    await self._reconcile_camera(camera, runtime.auto_start_enabled, now_local, session)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    detail = str(exc)[-500:] or exc.__class__.__name__
                    errors.append(f"camera {camera.id}: {detail}")
                    self._managed.discard(camera.id)
                    self._camera_status[camera.id] = {
                        "camera_id": camera.id,
                        "enabled": camera.enabled,
                        "auto_record": camera.auto_record,
                        "schedule_enabled": camera.recording_schedule_enabled,
                        "schedule": schedule_label(camera),
                        "schedule_state": "error",
                        "in_window": recording_schedule_allows(camera, now_local),
                        "auto_eligible": False,
                        "running": recorder_manager.is_running(camera.id),
                        "mode": "automatic",
                        "error": detail,
                    }
                    add_event(
                        session,
                        level="error",
                        category="recorder",
                        code="recorder.schedule_reconcile_failed",
                        message=f"摄像头 {camera.name} 录制计划校准失败: {detail}",
                        camera_id=camera.id,
                    )
            await session.commit()

        self._last_check_at = datetime.now(timezone.utc).isoformat()
        self._last_error = "; ".join(errors)[-1000:] if errors else None

    async def _reconcile_camera(
        self,
        camera: Camera,
        global_auto_start: bool,
        now_local: datetime,
        session,
    ) -> None:
        in_window = recording_schedule_allows(camera, now_local)
        running = recorder_manager.is_running(camera.id)
        auto_eligible = bool(
            global_auto_start and camera.enabled and camera.auto_record and in_window
        )

        if not camera.enabled:
            self.clear_override(camera.id)
            if running:
                await recorder_manager.stop(camera.id)
                running = False

        if camera.id in self._managed and not running and auto_eligible:
            self._managed.discard(camera.id)
            self._manual_paused.add(camera.id)

        if camera.id in self._manual_paused and not in_window:
            self._manual_paused.discard(camera.id)

        if not camera.enabled or not camera.auto_record:
            schedule_state = "disabled"
        elif not global_auto_start:
            schedule_state = "global_disabled"
        elif camera.recording_schedule_enabled:
            schedule_state = "in_window" if in_window else "scheduled"
        else:
            schedule_state = "automatic"

        if camera.id in self._manual_running:
            mode = "manual"
            schedule_state = "manual_override"
        elif camera.id in self._manual_paused:
            mode = "manual_paused"
            schedule_state = "manual_paused"
        else:
            mode = "automatic"
            if auto_eligible and not running:
                if camera.timestamp_mode == "reconstruct" and (
                    not camera.fps_num or not camera.fps_den
                ):
                    schedule_state = "probe_required"
                else:
                    try:
                        # Explicit schedules segment relative to actual start time;
                        # 24/7 auto-record preserves the global clock alignment.
                        align_override = False if camera.recording_schedule_enabled else None
                        await recorder_manager.start(
                            runtime_config(camera, align_segments_to_clock=align_override)
                        )
                        self._managed.add(camera.id)
                        running = True
                        add_event(
                            session,
                            level="info",
                            category="recorder",
                            code="recorder.schedule_started",
                            message=f"摄像头 {camera.name} 进入录制时段，自动开始录像",
                            camera_id=camera.id,
                            metadata={"schedule": schedule_label(camera)},
                        )
                    except Exception as exc:
                        schedule_state = "error"
                        add_event(
                            session,
                            level="error",
                            category="recorder",
                            code="recorder.schedule_start_failed",
                            message=f"摄像头 {camera.name} 计划录像启动失败: {str(exc)[-500:]}",
                            camera_id=camera.id,
                        )
            elif not auto_eligible and running and camera.id in self._managed:
                await recorder_manager.stop(camera.id)
                self._managed.discard(camera.id)
                running = False
                add_event(
                    session,
                    level="info",
                    category="recorder",
                    code="recorder.schedule_stopped",
                    message=f"摄像头 {camera.name} 离开录制时段，自动停止录像",
                    camera_id=camera.id,
                    metadata={"schedule": schedule_label(camera)},
                )

        self._camera_status[camera.id] = {
            "camera_id": camera.id,
            "enabled": camera.enabled,
            "auto_record": camera.auto_record,
            "schedule_enabled": camera.recording_schedule_enabled,
            "schedule": schedule_label(camera),
            "schedule_state": schedule_state,
            "in_window": in_window,
            "auto_eligible": auto_eligible,
            "running": recorder_manager.is_running(camera.id),
            "mode": mode,
        }


recording_schedule_manager = RecordingScheduleManager()
