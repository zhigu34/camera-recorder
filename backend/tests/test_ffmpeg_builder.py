from pathlib import Path

from app.services.ffmpeg_builder import CameraRuntimeConfig, build_record_command


def test_reconstruct_command_uses_detected_media_clock(tmp_path: Path):
    camera = CameraRuntimeConfig(
        id=1,
        name="test",
        ip="192.0.2.10",
        rtsp_port=554,
        username="admin",
        password="secret",
        rtsp_path="/ch1/main",
        timestamp_mode="reconstruct",
        fps_num=20,
        fps_den=1,
        audio_codec="aac",
        sample_rate=16000,
        audio_frame_samples=1024,
    )

    command = build_record_command(camera, tmp_path)
    joined = " ".join(command)

    assert "time_base=1/20:prescale=1" in joined
    assert "ts=N*1024:duration=1024:time_base=1/16000:prescale=1" in joined
    assert "-rtsp_transport tcp" in joined
    assert "-c:v copy" in joined
    assert "-c:a copy" in joined
    assert "-segment_time 600" in joined
