from app.services.preview_wall import JpegFrameParser, build_wall_preview_command


def test_jpeg_frame_parser_handles_split_and_multiple_frames():
    parser = JpegFrameParser()
    frame1 = b"\xff\xd8abc\xff\xd9"
    frame2 = b"\xff\xd8defgh\xff\xd9"

    assert parser.feed(b"noise\xff\xd8a") == []
    assert parser.feed(b"bc\xff\xd9" + frame2[:4]) == [frame1]
    assert parser.feed(frame2[4:]) == [frame2]


def test_wall_preview_command_uses_image2pipe_and_requested_profile():
    command = build_wall_preview_command(
        ip="192.0.2.10",
        port=554,
        username="user",
        password="pass",
        rtsp_path="/sub",
        rtsp_timeout_us=5_000_000,
        fps=3,
        width=480,
    )

    assert "image2pipe" in command
    assert "fps=3,scale='min(480,iw)':-2" in command
    assert "-rtsp_transport" in command
    assert "tcp" in command
