from pathlib import Path

from app.services.ffmpeg_builder import CameraRuntimeConfig, build_record_command
from app.services.media_input import MediaInput
from app.services.system_settings import RuntimeSettings


def make_camera(**overrides) -> CameraRuntimeConfig:
    values = {
        "id": 1,
        "name": "test",
        "stream_uri": "rtsp://admin:secret@192.0.2.10:554/ch1/main",
        "timestamp_mode": "native",
        "fps_num": 20,
        "fps_den": 1,
        "audio_codec": "aac",
        "sample_rate": 16000,
        "audio_frame_samples": 1024,
    }
    values.update(overrides)
    return CameraRuntimeConfig(**values)


def test_record_command_accepts_transport_neutral_media_input(tmp_path: Path) -> None:
    camera = make_camera(stream_uri=None)
    runtime = RuntimeSettings(segment_duration_seconds=60, rtsp_timeout_us=5_000_000)
    media_input = MediaInput(
        transport_args=("-rw_timeout", "5000000"),
        uri="http://hik-bridge:8100/streams/opaque-123/media",
    )

    command = build_record_command(camera, tmp_path, runtime, media_input=media_input)

    assert "-rtsp_transport" not in command
    assert command[command.index("-rw_timeout") + 1] == "5000000"
    assert command[command.index("-i") + 1] == media_input.uri


def test_record_command_keeps_legacy_rtsp_input_when_no_media_input_is_supplied(tmp_path: Path) -> None:
    camera = make_camera()
    runtime = RuntimeSettings(segment_duration_seconds=60, rtsp_timeout_us=5_000_000)

    command = build_record_command(camera, tmp_path, runtime)

    assert command[command.index("-rtsp_transport") + 1] == "tcp"
    assert command[command.index("-i") + 1] == camera.stream_uri
