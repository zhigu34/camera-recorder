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


def _patch_stop_dependencies(monkeypatch, calls: list[str], *, running=True, owner="manual"):
    monkeypatch.setattr(
        runtime_module.recording_schedule_manager,
        "recording_owner",
        lambda camera_id: owner if camera_id == 7 else None,
    )
    monkeypatch.setattr(runtime_module.recorder_manager, "is_running", lambda camera_id: running)

    async def stop_media(camera_id: int) -> None:
        calls.append(f"media-stop:{camera_id}")

    async def stop_motion(camera_id: int) -> None:
        calls.append(f"motion-stop:{camera_id}")

    def end_event(camera_id: int) -> None:
        calls.append(f"event-end:{camera_id}")

    async def stop_event(camera_id: int) -> None:
        calls.append(f"event-stop:{camera_id}")

    async def stop_recorder(camera_id: int):
        calls.append(f"recorder-stop:{camera_id}")
        return {"camera_id": camera_id, "state": "STOPPED"}

    def detach(camera_id: int) -> None:
        calls.append(f"schedule-detach:{camera_id}")

    def forget(camera_id: int) -> None:
        calls.append(f"schedule-forget:{camera_id}")

    monkeypatch.setattr(
        runtime_module,
        "camera_media_session_registry",
        SimpleNamespace(stop_camera=stop_media),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.motion_detection_manager, "stop_camera", stop_motion)
    monkeypatch.setattr(runtime_module.event_recording_manager, "end_event", end_event)
    monkeypatch.setattr(runtime_module.event_recording_manager, "stop_camera", stop_event)
    monkeypatch.setattr(runtime_module.recorder_manager, "stop", stop_recorder)
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "detach_for_runtime_reload", detach)
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "forget", forget)


@pytest.mark.asyncio
async def test_stop_all_snapshots_owner_and_stops_device_runtime(monkeypatch) -> None:
    calls: list[str] = []
    _patch_stop_dependencies(monkeypatch, calls, running=True, owner="manual")

    coordinator = runtime_module.CameraRuntimeCoordinator()
    snapshot = await coordinator.stop_all(7)

    assert snapshot.was_recording is True
    assert snapshot.recording_owner == "manual"
    assert calls == [
        "media-stop:7",
        "motion-stop:7",
        "event-end:7",
        "event-stop:7",
        "recorder-stop:7",
        "schedule-detach:7",
    ]


@pytest.mark.asyncio
async def test_stop_all_can_forget_schedule_state_for_delete(monkeypatch) -> None:
    calls: list[str] = []
    _patch_stop_dependencies(monkeypatch, calls, running=False, owner=None)

    coordinator = runtime_module.CameraRuntimeCoordinator()
    snapshot = await coordinator.stop_all(7, forget_schedule=True)

    assert snapshot.was_recording is False
    assert snapshot.recording_owner is None
    assert "recorder-stop:7" not in calls
    assert calls[-1] == "schedule-forget:7"
    assert "schedule-detach:7" not in calls


@pytest.mark.asyncio
async def test_reload_missing_camera_stays_stopped(monkeypatch) -> None:
    calls: list[str] = []
    _patch_stop_dependencies(monkeypatch, calls, running=False, owner=None)
    monkeypatch.setattr(runtime_module, "SessionLocal", lambda: _SessionContext(None))

    coordinator = runtime_module.CameraRuntimeCoordinator()
    result = await coordinator.reload(7)

    assert result == "missing"
    assert calls[-1] == "schedule-detach:7"


@pytest.mark.asyncio
async def test_reload_disabled_camera_forgets_runtime_state(monkeypatch) -> None:
    calls: list[str] = []
    _patch_stop_dependencies(monkeypatch, calls, running=True, owner="manual")
    monkeypatch.setattr(
        runtime_module,
        "SessionLocal",
        lambda: _SessionContext(SimpleNamespace(id=7, enabled=False)),
    )

    coordinator = runtime_module.CameraRuntimeCoordinator()
    result = await coordinator.reload(7)

    assert result == "disabled"
    assert calls[-1] == "schedule-forget:7"


@pytest.mark.asyncio
async def test_reload_restores_manual_recording_before_event_and_motion(monkeypatch) -> None:
    calls: list[str] = []
    _patch_stop_dependencies(monkeypatch, calls, running=True, owner="manual")
    camera = SimpleNamespace(id=7, enabled=True)
    monkeypatch.setattr(runtime_module, "SessionLocal", lambda: _SessionContext(camera))
    monkeypatch.setattr(runtime_module, "runtime_config", lambda item: ("runtime", item.id))

    async def start_regular(config):
        calls.append(f"recorder-start:{config[1]}")
        return {"camera_id": config[1], "state": "RECORDING"}

    def note_manual_start(camera_id: int) -> None:
        calls.append(f"schedule-manual:{camera_id}")

    async def reconcile_schedule() -> None:
        calls.append("schedule-reconcile")

    async def reconcile_event() -> int:
        calls.append("event-reconcile")
        return 1

    async def restart_motion(camera_id: int) -> None:
        calls.append(f"motion-restart:{camera_id}")

    monkeypatch.setattr(runtime_module, "start_regular_recorder", start_regular)
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "note_manual_start", note_manual_start)
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "reconcile", reconcile_schedule)
    monkeypatch.setattr(runtime_module.event_recording_manager, "reconcile_once", reconcile_event)
    monkeypatch.setattr(runtime_module.motion_detection_manager, "restart_camera", restart_motion)

    coordinator = runtime_module.CameraRuntimeCoordinator()
    result = await coordinator.reload(7)

    assert result == "running"
    assert "schedule-reconcile" not in calls
    assert calls[-4:] == [
        "recorder-start:7",
        "schedule-manual:7",
        "event-reconcile",
        "motion-restart:7",
    ]


@pytest.mark.asyncio
async def test_reload_schedule_owner_uses_reconcile_before_event_and_motion(monkeypatch) -> None:
    calls: list[str] = []
    _patch_stop_dependencies(monkeypatch, calls, running=True, owner="schedule")
    camera = SimpleNamespace(id=7, enabled=True)
    monkeypatch.setattr(runtime_module, "SessionLocal", lambda: _SessionContext(camera))

    async def reconcile_schedule() -> None:
        calls.append("schedule-reconcile")

    async def reconcile_event() -> int:
        calls.append("event-reconcile")
        return 1

    async def restart_motion(camera_id: int) -> None:
        calls.append(f"motion-restart:{camera_id}")

    async def unexpected_start(config):
        raise AssertionError(f"direct recorder restart not expected: {config}")

    monkeypatch.setattr(runtime_module.recording_schedule_manager, "reconcile", reconcile_schedule)
    monkeypatch.setattr(runtime_module.event_recording_manager, "reconcile_once", reconcile_event)
    monkeypatch.setattr(runtime_module.motion_detection_manager, "restart_camera", restart_motion)
    monkeypatch.setattr(runtime_module, "start_regular_recorder", unexpected_start)

    coordinator = runtime_module.CameraRuntimeCoordinator()
    result = await coordinator.reload(7)

    assert result == "running"
    assert calls[-3:] == ["schedule-reconcile", "event-reconcile", "motion-restart:7"]


@pytest.mark.asyncio
async def test_schedule_change_drops_manual_override_and_reconciles(monkeypatch) -> None:
    calls: list[str] = []
    _patch_stop_dependencies(monkeypatch, calls, running=True, owner="manual")
    camera = SimpleNamespace(id=7, enabled=True)
    monkeypatch.setattr(runtime_module, "SessionLocal", lambda: _SessionContext(camera))

    def reset(camera_id: int) -> None:
        calls.append(f"schedule-reset:{camera_id}")

    async def reconcile_schedule() -> None:
        calls.append("schedule-reconcile")

    async def reconcile_event() -> int:
        calls.append("event-reconcile")
        return 1

    async def restart_motion(camera_id: int) -> None:
        calls.append(f"motion-restart:{camera_id}")

    async def unexpected_start(config):
        raise AssertionError(f"manual recorder must not be restored after schedule edit: {config}")

    monkeypatch.setattr(runtime_module.recording_schedule_manager, "reset_for_schedule_change", reset)
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "reconcile", reconcile_schedule)
    monkeypatch.setattr(runtime_module.event_recording_manager, "reconcile_once", reconcile_event)
    monkeypatch.setattr(runtime_module.motion_detection_manager, "restart_camera", restart_motion)
    monkeypatch.setattr(runtime_module, "start_regular_recorder", unexpected_start)

    coordinator = runtime_module.CameraRuntimeCoordinator()
    result = await coordinator.reload(7, schedule_changed=True)

    assert result == "running"
    assert calls[-4:] == [
        "schedule-reset:7",
        "schedule-reconcile",
        "event-reconcile",
        "motion-restart:7",
    ]
