from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.event_recording import (
    build_event_buffer_command,
    event_clip_window,
    select_buffer_segments,
    should_buffer_event_camera,
)


def test_event_clip_window_includes_five_second_preroll() -> None:
    started_at = datetime(2026, 9, 15, 12, 0, 10, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(seconds=7)

    clip_start, clip_end = event_clip_window(started_at, ended_at)

    assert clip_start == started_at - timedelta(seconds=5)
    assert clip_end == ended_at


def test_regular_recorder_disables_event_ring_buffer() -> None:
    assert should_buffer_event_camera(
        camera_enabled=True,
        detection_enabled=True,
        recorder_running=False,
    ) is True
    assert should_buffer_event_camera(
        camera_enabled=True,
        detection_enabled=True,
        recorder_running=True,
    ) is False
    assert should_buffer_event_camera(
        camera_enabled=False,
        detection_enabled=True,
        recorder_running=False,
    ) is False
    assert should_buffer_event_camera(
        camera_enabled=True,
        detection_enabled=False,
        recorder_running=False,
    ) is False


def test_event_buffer_is_stream_copy_one_second_segments(tmp_path: Path) -> None:
    command = build_event_buffer_command(
        stream_uri="rtsp://admin:secret@10.0.0.8:554/main",
        output_dir=tmp_path,
        rtsp_timeout_us=5_000_000,
    )

    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "copy"
    assert command[command.index("-segment_time") + 1] == "1"
    assert str(tmp_path / "%Y-%m-%d_%H-%M-%S.mkv") == command[-1]


def test_segment_selection_covers_preroll_window(tmp_path: Path) -> None:
    paths = [
        tmp_path / "2026-09-15_12-00-04.mkv",
        tmp_path / "2026-09-15_12-00-05.mkv",
        tmp_path / "2026-09-15_12-00-06.mkv",
        tmp_path / "2026-09-15_12-00-07.mkv",
        tmp_path / "2026-09-15_12-00-08.mkv",
        tmp_path / "2026-09-15_12-00-09.mkv",
        tmp_path / "2026-09-15_12-00-10.mkv",
        tmp_path / "2026-09-15_12-00-11.mkv",
        tmp_path / "2026-09-15_12-00-12.mkv",
    ]
    clip_start = datetime(2026, 9, 15, 12, 0, 5, tzinfo=timezone.utc)
    clip_end = datetime(2026, 9, 15, 12, 0, 12, tzinfo=timezone.utc)

    selected = select_buffer_segments(paths, clip_start, clip_end)

    assert [path.name for path in selected] == [
        "2026-09-15_12-00-05.mkv",
        "2026-09-15_12-00-06.mkv",
        "2026-09-15_12-00-07.mkv",
        "2026-09-15_12-00-08.mkv",
        "2026-09-15_12-00-09.mkv",
        "2026-09-15_12-00-10.mkv",
        "2026-09-15_12-00-11.mkv",
        "2026-09-15_12-00-12.mkv",
    ]
