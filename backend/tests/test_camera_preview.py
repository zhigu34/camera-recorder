from app.services.camera_preview import (
    build_preview_command,
    infer_substream_path,
    resolve_preview_path,
)


def test_infer_common_substream_path() -> None:
    assert infer_substream_path("/ch1/main") == "/ch1/sub"
    assert infer_substream_path("/ch2/main") == "/ch2/sub"
    assert infer_substream_path("/Streaming/Channels/101") is None


def test_preview_auto_prefers_configured_or_inferred_substream() -> None:
    assert resolve_preview_path(
        main_path="/ch1/main",
        sub_path="/custom/sub",
        stream="auto",
    ) == ("/custom/sub", "sub")
    assert resolve_preview_path(
        main_path="/ch1/main",
        sub_path=None,
        stream="auto",
    ) == ("/ch1/sub", "sub")
    assert resolve_preview_path(
        main_path="/Streaming/Channels/101",
        sub_path=None,
        stream="auto",
    ) == ("/Streaming/Channels/101", "main")


def test_preview_command_uses_tcp_and_resource_limits() -> None:
    command = build_preview_command(
        ip="192.0.2.10",
        port=554,
        username="admin",
        password="p@ss word",
        rtsp_path="/ch1/sub",
        rtsp_timeout_us=5_000_000,
        fps=8,
        width=960,
    )

    assert command[0].endswith("ffmpeg")
    assert command[command.index("-rtsp_transport") + 1] == "tcp"
    assert command[command.index("-timeout") + 1] == "5000000"
    assert command[command.index("-vf") + 1] == "fps=8,scale='min(960,iw)':-2"
    assert command[command.index("-c:v") + 1] == "mjpeg"
    assert command[-2:] == ["mpjpeg", "pipe:1"]
    assert "rtsp://admin:p%40ss%20word@192.0.2.10:554/ch1/sub" in command
