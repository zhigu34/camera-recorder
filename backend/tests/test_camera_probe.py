import json

import pytest

from app.services.camera_probe import probe_camera


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = 0
        self.killed = False

    async def communicate(self):
        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "profile": "Main",
                    "width": 3840,
                    "height": 2160,
                    "avg_frame_rate": "15/1",
                    "pix_fmt": "yuv420p",
                    "has_b_frames": 0,
                    "time_base": "1/90000",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "profile": "LC",
                    "sample_rate": "16000",
                    "channels": 1,
                },
            ]
        }
        return json.dumps(payload).encode(), b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self):
        return 0


@pytest.mark.asyncio
async def test_probe_uses_supplied_rtsp_timeout(monkeypatch):
    captured: list[str] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured.extend(str(item) for item in args)
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    result = await probe_camera(
        ip="192.168.1.10",
        port=554,
        username="admin",
        password="secret",
        rtsp_path="/ch1/main",
        rtsp_timeout_us=7_500_000,
    )

    timeout_index = captured.index("-timeout")
    assert captured[timeout_index + 1] == "7500000"
    assert result["video_codec"] == "hevc"
    assert result["fps_num"] == 15
    assert result["fps_den"] == 1
    assert result["audio_codec"] == "aac"
    assert result["audio_frame_samples"] == 1024
