from pathlib import Path

from app.services.event_recording import build_event_buffer_command


def test_event_buffer_http_media_input_does_not_receive_rtsp_options(tmp_path: Path) -> None:
    uri = "http://127.0.0.1:8000/internal/hik-media/7/main"
    command = build_event_buffer_command(
        stream_uri=uri,
        output_dir=tmp_path,
        rtsp_timeout_us=5_000_000,
    )

    assert "-rtsp_transport" not in command
    assert command[command.index("-rw_timeout") + 1] == "5000000"
    assert command[command.index("-i") + 1] == uri
