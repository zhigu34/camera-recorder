from app.services.motion_worker import build_motion_command


def test_motion_http_media_input_does_not_receive_rtsp_options() -> None:
    uri = "http://127.0.0.1:8000/internal/hik-media/7/sub"
    command = build_motion_command(
        stream_uri=uri,
        rtsp_timeout_us=5_000_000,
        fps=4,
        width=640,
    )

    assert "-rtsp_transport" not in command
    assert command[command.index("-rw_timeout") + 1] == "5000000"
    assert command[command.index("-i") + 1] == uri
