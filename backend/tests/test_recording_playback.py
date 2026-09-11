import asyncio
import os
import time
from pathlib import Path

import pytest

from app.services.recording_playback import RecordingPlaybackManager


def test_h264_is_direct_playback(tmp_path):
    manager = RecordingPlaybackManager()
    manager.proxy_dir = tmp_path

    state = manager.status(1, "h264")

    assert state["state"] == "direct"
    assert state["direct"] is True
    assert list(tmp_path.iterdir()) == []


def test_hevc_can_try_original_without_being_guaranteed_direct():
    manager = RecordingPlaybackManager()

    assert manager.can_try_original("hevc") is True
    assert manager.can_try_original("hvc1") is True
    assert manager.can_direct_play("hevc") is False


def test_proxy_command_copies_aac_audio(tmp_path):
    source = tmp_path / "source.mp4"
    target = tmp_path / "target.mp4"

    command = RecordingPlaybackManager.build_proxy_command(source, target, "aac")

    audio_index = command.index("-c:a")
    assert command[audio_index + 1] == "copy"
    assert "-pix_fmt" in command
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"


def test_proxy_command_transcodes_non_aac_audio(tmp_path):
    source = tmp_path / "source.mp4"
    target = tmp_path / "target.mp4"

    command = RecordingPlaybackManager.build_proxy_command(source, target, "pcm_alaw")

    audio_index = command.index("-c:a")
    assert command[audio_index + 1] == "aac"
    assert "96k" in command


def test_live_proxy_command_is_fragmented_and_low_latency(tmp_path):
    source = tmp_path / "source.mp4"

    command = RecordingPlaybackManager.build_live_proxy_command(source, "aac")

    assert command[-2:] == ["mp4", "pipe:1"]
    assert command[command.index("-tune") + 1] == "zerolatency"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-c:a") + 1] == "copy"
    movflags = command[command.index("-movflags") + 1]
    assert "frag_keyframe" in movflags
    assert "empty_moov" in movflags
    assert "default_base_moof" in movflags
    assert "-force_key_frames" in command


def test_live_proxy_status_is_visible():
    manager = RecordingPlaybackManager()
    manager._live_ids.add(77)

    state = manager.status(77, "hevc")

    assert state["state"] == "streaming"
    assert state["direct"] is False


@pytest.mark.asyncio
async def test_live_proxy_streams_first_bytes_and_caches(monkeypatch, tmp_path):
    manager = RecordingPlaybackManager()
    manager.proxy_dir = tmp_path / "proxies"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"hevc-source")

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(b"fragmented-mp4")
            self.stdout.feed_eof()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()

        async def wait(self):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    async def fake_create_subprocess_exec(*command, **kwargs):
        return FakeProcess()

    async def fake_finalize(recording_id: int, live_temp: Path):
        target = manager.proxy_path(recording_id)
        live_temp.replace(target)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(manager, "_finalize_live_cache", fake_finalize)

    session = await manager.open_live_proxy(55, source, "aac")
    assert session is not None
    assert manager.status(55, "hevc")["state"] == "streaming"

    chunks = []
    async for chunk in session.stream():
        chunks.append(chunk)

    assert b"".join(chunks) == b"fragmented-mp4"
    assert manager.proxy_path(55).read_bytes() == b"fragmented-mp4"
    assert manager.status(55, "hevc")["state"] == "ready"


@pytest.mark.asyncio
async def test_hevc_proxy_generation_is_atomic(monkeypatch, tmp_path):
    manager = RecordingPlaybackManager()
    manager.proxy_dir = tmp_path / "proxies"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"hevc-source")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*command, **kwargs):
        Path(command[-1]).write_bytes(b"proxy-data")
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    state = await manager.start(42, source, "hevc", "aac")
    assert state["state"] == "generating"

    for _ in range(100):
        if manager.status(42, "hevc")["state"] == "ready":
            break
        await asyncio.sleep(0.01)

    final = manager.status(42, "hevc")
    assert final["state"] == "ready"
    assert manager.proxy_path(42).read_bytes() == b"proxy-data"
    assert not manager.proxy_path(42).with_suffix(".part.mp4").exists()


def test_old_proxy_cache_is_removed(tmp_path):
    manager = RecordingPlaybackManager()
    manager.proxy_dir = tmp_path
    old = manager.proxy_path(7)
    recent = manager.proxy_path(8)
    old.write_bytes(b"old")
    recent.write_bytes(b"recent")

    stale = time.time() - (25 * 3600)
    os.utime(old, (stale, stale))

    manager._cleanup_old_sync()

    assert not old.exists()
    assert recent.exists()
