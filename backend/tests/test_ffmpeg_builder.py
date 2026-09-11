from pathlib import Path

from app.services.ffmpeg_builder import CameraRuntimeConfig, build_record_command
from app.services.system_settings import RuntimeSettings


def make_camera(**overrides) -> CameraRuntimeConfig:
    values = {
        "id": 1,
        "name": "test",
        "ip": "192.0.2.10",
        "rtsp_port": 554,
        "username": "admin",
        "password": "secret",
        "rtsp_path": "/ch1/main",
        "timestamp_mode": "reconstruct",
        "fps_num": 20,
        "fps_den": 1,
        "audio_codec": "aac",
        "sample_rate": 16000,
        "audio_frame_samples": 1024,
    }
    values.update(overrides)
    return CameraRuntimeConfig(**values)


def test_reconstruct_command_uses_detected_media_clock(tmp_path: Path):
    camera = make_camera()
    runtime = RuntimeSettings(
        segment_duration_seconds=600,
        rtsp_timeout_us=5_000_000,
        align_segments_to_clock=True,
    )

    command = build_record_command(camera, tmp_path, runtime)
    joined = " ".join(command)

    assert "time_base=1/20:prescale=1" in joined
    assert "ts=N*1024:duration=1024:time_base=1/16000:prescale=1" in joined
    assert "-rtsp_transport tcp" in joined
    assert "-c:v copy" in joined
    assert "-c:a copy" in joined
    assert "-segment_time 600" in joined
    assert "-segment_atclocktime 1" in joined


def test_scheduled_recording_can_disable_clock_alignment(tmp_path: Path):
    camera = make_camera(align_segments_to_clock=False)
    runtime = RuntimeSettings(
        segment_duration_seconds=600,
        align_segments_to_clock=True,
    )

    command = build_record_command(camera, tmp_path, runtime)

    assert "-segment_time" in command
    assert "600" in command
    assert "-segment_atclocktime" not in command
