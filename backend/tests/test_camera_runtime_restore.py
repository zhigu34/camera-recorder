from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import camera_runtime_coordinator as runtime_module


class _Db:
    def __init__(self, camera) -> None:
        self.camera = camera

    async def get(self, model, camera_id: int):
        del model, camera_id
        return self.camera


class _SessionContext:
    def __init__(self, camera) -> None:
        self.db = _Db(camera)

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _patch_restore_dependencies(monkeypatch, calls: list[str]) -> None:
    async def start_regular(config):
        calls.append(f"recorder-start:{config[1]}")
        return {"camera_id": config[1], "state": "RECORDING"}

    def note_manual_start(camera_id: int) -> None:
        calls.append(f"schedule-manual:{camera_id}")

    def reset(camera_id: int) -> None:
        calls.append(f"schedule-reset:{camera_id}")

    async def reconcile_schedule() -> None:
        calls.append("schedule-reconcile")

    async def reconcile_event() -> int:
        calls.append("event-reconcile")
        return 1

    async def restart_motion(camera_id: int) -> None:
        calls.append(f"motion-restart:{camera_id}")

    monkeypatch.setattr(runtime_module, "runtime_config", lambda item: ("runtime", item.id))
    monkeypatch.setattr(runtime_module, "start_regular_recorder", start_regular)
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "note_manual_start", note_manual_start)
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "reset_for_schedule_change", reset)
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "reconcile", reconcile_schedule)
    monkeypatch.setattr(runtime_module.event_recording_manager, "reconcile_once", reconcile_event)
    monkeypatch.setattr(runtime_module.motion_detection_manager, "restart_camera", restart_motion)


@pytest.mark.asyncio
async def test_restore_manual_snapshot_does_not_stop_runtime_again(monkeypatch) -> None:
    calls: list[str] = []
    camera = SimpleNamespace(id=7, enabled=True)
    monkeypatch.setattr(runtime_module, "SessionLocal", lambda: _SessionContext(camera))
    _patch_restore_dependencies(monkeypatch, calls)

    coordinator = runtime_module.CameraRuntimeCoordinator()

    async def unexpected_stop(*args, **kwargs):
        raise AssertionError(f"restore must not call stop_all again: {args!r} {kwargs!r}")

    monkeypatch.setattr(coordinator, "stop_all", unexpected_stop)
    snapshot = runtime_module.RuntimeStopSnapshot(was_recording=True, recording_owner="manual")

    result = await coordinator.restore(7, snapshot)

    assert result == "running"
    assert calls == [
        "recorder-start:7",
        "schedule-manual:7",
        "event-reconcile",
        "motion-restart:7",
    ]


@pytest.mark.asyncio
async def test_restore_schedule_change_reconciles_without_second_stop(monkeypatch) -> None:
    calls: list[str] = []
    camera = SimpleNamespace(id=7, enabled=True)
    monkeypatch.setattr(runtime_module, "SessionLocal", lambda: _SessionContext(camera))
    _patch_restore_dependencies(monkeypatch, calls)

    coordinator = runtime_module.CameraRuntimeCoordinator()

    async def unexpected_stop(*args, **kwargs):
        raise AssertionError(f"restore must not call stop_all again: {args!r} {kwargs!r}")

    monkeypatch.setattr(coordinator, "stop_all", unexpected_stop)
    snapshot = runtime_module.RuntimeStopSnapshot(was_recording=True, recording_owner="manual")

    result = await coordinator.restore(7, snapshot, schedule_changed=True)

    assert result == "running"
    assert calls == [
        "schedule-reset:7",
        "schedule-reconcile",
        "event-reconcile",
        "motion-restart:7",
    ]
