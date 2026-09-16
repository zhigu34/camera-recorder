from app.services.camera_preview import build_preview_command


def test_preview_http_media_input_does_not_receive_rtsp_options() -> None:
    uri = "http://127.0.0.1:8000/internal/hik-media/7/sub"
    command = build_preview_command(
        stream_uri=uri,
        rtsp_timeout_us=5_000_000,
        fps=8,
        width=960,
    )

    assert "-rtsp_transport" not in command
    assert command[command.index("-rw_timeout") + 1] == "5000000"
    assert command[command.index("-i") + 1] == uri
