from types import SimpleNamespace

import pytest

import app.services.event_recording as event_recording_module
import app.services.recorder_manager as recorder_manager_module
from app.services.recorder_manager import RecorderManager


@pytest.mark.asyncio
async def test_regular_recorder_stops_event_buffer_before_start(monkeypatch) -> None:
    calls: list[str] = []

    async def stop_event_buffer(camera_id: int) -> None:
        assert camera_id == 17
        calls.append("event-buffer-stop")

    class FakeCameraWorker:
        def __init__(self, camera) -> None:
            self.camera = camera
            self.running = False

        async def start(self) -> None:
            calls.append("regular-recorder-start")
            self.running = True

        def snapshot(self) -> dict:
            return {"camera_id": self.camera.id, "state": "RECORDING", "pid": 1}

    monkeypatch.setattr(
        event_recording_module.event_recording_manager,
        "stop_camera",
        stop_event_buffer,
    )
    monkeypatch.setattr(recorder_manager_module, "CameraWorker", FakeCameraWorker)

    manager = RecorderManager()
    result = await manager.start(SimpleNamespace(id=17))

    assert result["state"] == "RECORDING"
    assert calls == ["event-buffer-stop", "regular-recorder-start"]
