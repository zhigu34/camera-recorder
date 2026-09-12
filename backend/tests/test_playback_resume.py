import asyncio
from pathlib import Path

import pytest

from app.services.recording_playback import RecordingPlaybackManager


def test_live_proxy_command_seeks_to_resume_position_before_input(tmp_path: Path):
    source = tmp_path / "source.mp4"

    command = RecordingPlaybackManager.build_live_proxy_command(
        source,
        "aac",
        start_seconds=123.456,
    )

    assert command[command.index("-ss") + 1] == "123.456"
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-i") + 1] == str(source)


def test_live_proxy_progress_keeps_source_timeline_after_resume():
    manager = RecordingPlaybackManager()
    manager._live_ids.add(77)
    manager._start_progress(77, 600, "live", source_offset_seconds=300)
    manager._update_progress(77, 12.5)

    state = manager.status(77, "hevc")
    progress = state["progress"]

    assert progress["source_offset_seconds"] == 300.0
    assert progress["elapsed_seconds"] == 312.5
    assert progress["duration_seconds"] == 600.0
    assert progress["percent"] == 52.1


@pytest.mark.asyncio
async def test_resumed_live_proxy_is_not_saved_as_complete_cache(monkeypatch, tmp_path: Path):
    manager = RecordingPlaybackManager()
    manager.proxy_dir = tmp_path / "proxies"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"hevc-source")
    commands: list[tuple[str, ...]] = []
    finalized = False

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(b"resumed-fragment")
            self.stdout.feed_eof()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_data(b"out_time_us=10000000\nprogress=end\n")
            self.stderr.feed_eof()

        async def wait(self):
            await asyncio.sleep(0)
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    async def fake_create_subprocess_exec(*command, **kwargs):
        commands.append(tuple(str(value) for value in command))
        return FakeProcess()

    async def fake_finalize(recording_id: int, live_temp: Path):
        nonlocal finalized
        finalized = True

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(manager, "_finalize_live_cache", fake_finalize)

    session = await manager.open_live_proxy(
        55,
        source,
        "aac",
        duration_seconds=600,
        start_seconds=240,
    )
    assert session is not None

    chunks = []
    async for chunk in session.stream():
        chunks.append(chunk)

    assert b"".join(chunks) == b"resumed-fragment"
    assert finalized is False
    assert not manager.proxy_path(55).exists()
    assert not manager.live_temp_path(55).exists()
    assert commands
    command = commands[0]
    assert command[command.index("-ss") + 1] == "240.000"
    assert command.index("-ss") < command.index("-i")
