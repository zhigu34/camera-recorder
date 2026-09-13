from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from app.services import recording_export as exports


def test_concat_file_line_escapes_quotes_and_spaces():
    line = exports.concat_file_line(Path("/recordings/cam a/door's clip.mp4"))
    assert line == "file '/recordings/cam a/door'\\''s clip.mp4'"


def test_fast_group_command_uses_stream_copy_and_requested_trim():
    command = exports.build_fast_group_command(
        Path("/tmp/sources.txt"),
        Path("/tmp/group.part.mp4"),
        start_offset_seconds=12.5,
        duration_seconds=83.25,
    )

    joined = " ".join(command)
    assert "-f concat" in joined
    assert "-safe 0" in joined
    assert "-ss 12.500" in joined
    assert "-t 83.250" in joined
    assert "-c copy" in joined
    assert "-avoid_negative_ts make_zero" in joined
    assert command[-1] == "/tmp/group.part.mp4"


def test_exact_group_command_reencodes_video_and_audio():
    command = exports.build_exact_group_command(
        Path("/tmp/sources.txt"),
        Path("/tmp/group.part.mp4"),
        start_offset_seconds=1.25,
        duration_seconds=9.5,
    )
    joined = " ".join(command)
    assert "-c:v libx264" in joined
    assert "-c:a aac" in joined
    assert "-ss 1.250" in joined
    assert "-t 9.500" in joined


def test_merge_groups_command_is_stream_copy():
    command = exports.build_merge_groups_command(
        Path("/tmp/groups.txt"), Path("/tmp/final.part.mp4")
    )
    joined = " ".join(command)
    assert "-f concat" in joined
    assert "-c copy" in joined
    assert command[-1] == "/tmp/final.part.mp4"


def test_zip_bundle_uses_store_mode_and_writes_manifest(tmp_path):
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    first.write_bytes(b"a" * 8)
    second.write_bytes(b"b" * 8)
    output = tmp_path / "bundle.zip"
    manifest = {
        "requested_start": "2026-09-14T10:00:00+00:00",
        "requested_end": "2026-09-14T10:15:00+00:00",
    }

    exports.create_zip_bundle(output, [first, second], manifest)

    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {"a.mp4", "b.mp4", "export-info.json"}
        assert all(item.compress_type == ZIP_STORED for item in archive.infolist())
        assert b"requested_start" in archive.read("export-info.json")
