from types import SimpleNamespace

import pytest

from app.services.camera_probe import probe_camera_media


@pytest.mark.asyncio
async def test_probe_camera_media_resolves_hik_recording_source(monkeypatch):
    camera = SimpleNamespace(
        id=17,
        connection_type="hik_sdk",
        hik_metadata=SimpleNamespace(),
    )
    captured: dict[str, object] = {}

    async def fake_probe_stream_uri(*, stream_uri: str, rtsp_timeout_us: int):
        captured["stream_uri"] = stream_uri
        captured["rtsp_timeout_us"] = rtsp_timeout_us
        return {"ok": True, "video_codec": "h264"}

    monkeypatch.setattr(
        "app.services.camera_probe.probe_stream_uri",
        fake_probe_stream_uri,
    )

    result = await probe_camera_media(camera, rtsp_timeout_us=7_500_000)

    assert captured == {
        "stream_uri": "http://127.0.0.1:8000/internal/hik-media/17/main",
        "rtsp_timeout_us": 7_500_000,
    }
    assert result["video_codec"] == "h264"
