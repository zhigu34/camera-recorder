import inspect
from types import SimpleNamespace

import pytest

import app.services.recording_start as recording_start_module
from app.api import recorder as recorder_api_module
from app.services import recording_schedule_manager as schedule_module


@pytest.mark.asyncio
async def test_regular_recorder_stops_event_buffer_before_start(monkeypatch) -> None:
    calls: list[str] = []

    async def stop_event_buffer(camera_id: int) -> None:
        assert camera_id == 17
        calls.append("event-buffer-stop")

    async def start_recorder(camera) -> dict:
        assert camera.id == 17
        calls.append("regular-recorder-start")
        return {"camera_id": 17, "state": "RECORDING", "pid": 1}

    monkeypatch.setattr(
        recording_start_module.event_recording_manager,
        "stop_camera",
        stop_event_buffer,
    )
    monkeypatch.setattr(recording_start_module.recorder_manager, "start", start_recorder)

    result = await recording_start_module.start_regular_recorder(SimpleNamespace(id=17))

    assert result["state"] == "RECORDING"
    assert calls == ["event-buffer-stop", "regular-recorder-start"]


def test_manual_and_scheduled_starts_use_handoff_entrypoint() -> None:
    api_source = inspect.getsource(recorder_api_module)
    schedule_source = inspect.getsource(schedule_module)

    assert "start_regular_recorder(" in api_source
    assert "start_regular_recorder(" in schedule_source
    assert "recorder_manager.start(" not in api_source
    assert "recorder_manager.start(" not in schedule_source
