from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import camera_runtime_coordinator as runtime_module


class _Db:
    async def get(self, _model, camera_id: int):
        return SimpleNamespace(id=camera_id, enabled=True)


class _SessionContext:
    async def __aenter__(self):
        return _Db()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_restore_does_not_touch_media_session_registry(monkeypatch) -> None:
    async def unexpected_media_stop(camera_id: int) -> None:
        raise AssertionError(f"restore must not stop media sessions: {camera_id}")

    async def unexpected_stop_all(*args, **kwargs):
        raise AssertionError(f"restore must not call stop_all: {args}, {kwargs}")

    async def reconcile_schedule() -> None:
        return None

    async def reconcile_event() -> int:
        return 1

    async def restart_motion(_camera_id: int) -> None:
        return None

    monkeypatch.setattr(runtime_module, "SessionLocal", lambda: _SessionContext())
    monkeypatch.setattr(
        runtime_module,
        "camera_media_session_registry",
        SimpleNamespace(stop_camera=unexpected_media_stop),
        raising=False,
    )
    monkeypatch.setattr(
        runtime_module.CameraRuntimeCoordinator,
        "stop_all",
        unexpected_stop_all,
    )
    monkeypatch.setattr(runtime_module.recording_schedule_manager, "reconcile", reconcile_schedule)
    monkeypatch.setattr(runtime_module.event_recording_manager, "reconcile_once", reconcile_event)
    monkeypatch.setattr(runtime_module.motion_detection_manager, "restart_camera", restart_motion)

    coordinator = runtime_module.CameraRuntimeCoordinator()
    result = await coordinator.restore(
        7,
        runtime_module.RuntimeStopSnapshot(
            was_recording=False,
            recording_owner=None,
        ),
    )

    assert result == "running"
