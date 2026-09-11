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
    assert state["progress"] is None
    assert list(tmp_path.iterdir()) == []


def test_existing_compatibility_proxy_wins_over_h264_direct_play(tmp_path):
    manager = RecordingPlaybackManager()
    manager.proxy_dir = tmp_path
    manager.proxy_path(1).write_bytes(b"browser-compatible-proxy")

    state = manager.status(1, "h264")

    assert state["state"] == "ready"
    assert state["direct"] is False


def test_hevc_can_try_original_without_being_guaranteed_direct():
    manager = RecordingPlaybackManager()

    assert manager.can_try_original("hevc") is True
    assert manager.can_try_original("hvc1") is True
    assert manager.can_direct_play("hevc") is False


def test_proxy_command_normalizes_aac_and_keeps_1080p_quality(tmp_path):
    source = tmp_path / "source.mp4"
    target = tmp_path / "target.mp4"

    command = RecordingPlaybackManager.build_proxy_command(source, target, "aac")

    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-profile:a") + 1] == "aac_low"
    assert command[command.index("-b:a") + 1] == "128k"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-vf") + 1] == "scale='min(1920,iw)':-2"
    assert command[command.index("-crf") + 1] == "20"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-threads") + 1] == "4"
    assert command[command.index("-progress") + 1] == "pipe:2"
    assert "-nostats" in command


def test_proxy_command_normalizes_non_aac_audio(tmp_path):
    source = tmp_path / "source.mp4"
    target = tmp_path / "target.mp4"

    command = RecordingPlaybackManager.build_proxy_command(source, target, "pcm_alaw")

    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-profile:a") + 1] == "aac_low"
    assert command[command.index("-b:a") + 1] == "128k"
    assert command[command.index("-ar") + 1] == "48000"


def test_live_proxy_command_is_fragmented_low_latency_and_high_quality(tmp_path):
    source = tmp_path / "source.mp4"

    command = RecordingPlaybackManager.build_live_proxy_command(source, "aac")

    assert command[-2:] == ["mp4", "pipe:1"]
    assert command[command.index("-tune") + 1] == "zerolatency"
    assert command[command.index("-vf") + 1] == "scale='min(1920,iw)':-2"
    assert command[command.index("-crf") + 1] == "21"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-threads") + 1] == "4"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-profile:a") + 1] == "aac_low"
    assert command[command.index("-b:a") + 1] == "128k"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-progress") + 1] == "pipe:2"
    movflags = command[command.index("-movflags") + 1]
    assert "frag_keyframe" in movflags
    assert "empty_moov" in movflags
    assert "default_base_moof" in movflags
    assert "-force_key_frames" in command


def test_live_proxy_command_accepts_remote_url():
    remote = "http://127.0.0.1:8000/api/recordings/77/cloud-stream"

    command = RecordingPlaybackManager.build_live_proxy_command(remote, "aac")

    assert command[command.index("-i") + 1] == remote
    assert command[command.index("-c:a") + 1] == "aac"


def test_live_proxy_status_includes_progress():
    manager = RecordingPlaybackManager()
    manager._live_ids.add(77)
    manager._start_progress(77, 600, "live")
    manager._update_progress(77, 123.4)

    state = manager.status(77, "hevc")

    assert state["state"] == "streaming"
    assert state["direct"] is False
    assert state["progress"]["mode"] == "live"
    assert state["progress"]["elapsed_seconds"] == 123.4
    assert state["progress"]["duration_seconds"] == 600.0
    assert state["progress"]["percent"] == 20.6
    assert state["progress"]["cancellable"] is True


@pytest.mark.asyncio
async def test_live_proxy_streams_first_bytes_tracks_progress_and_caches(monkeypatch, tmp_path):
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
            self.stderr.feed_data(b"out_time_us=300000000\nprogress=continue\n")
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
        return FakeProcess()

    async def fake_finalize(recording_id: int, live_temp: Path):
        target = manager.proxy_path(recording_id)
        live_temp.replace(target)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(manager, "_finalize_live_cache", fake_finalize)

    session = await manager.open_live_proxy(55, source, "aac", duration_seconds=600)
    assert session is not None
    await asyncio.sleep(0)
    state = manager.status(55, "hevc")
    assert state["state"] == "streaming"
    assert state["progress"]["percent"] == 50.0

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
        def __init__(self):
            self.returncode = None
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_data(b"out_time_us=600000000\nprogress=end\n")
            self.stderr.feed_eof()
            self.target = None

        async def wait(self):
            await asyncio.sleep(0)
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    async def fake_create_subprocess_exec(*command, **kwargs):
        process = FakeProcess()
        Path(command[-1]).write_bytes(b"proxy-data")
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    state = await manager.start(42, source, "hevc", "aac", duration_seconds=600)
    assert state["state"] == "generating"

    for _ in range(100):
        if manager.status(42, "hevc")["state"] == "ready":
            break
        await asyncio.sleep(0.01)

    final = manager.status(42, "hevc")
    assert final["state"] == "ready"
    assert manager.proxy_path(42).read_bytes() == b"proxy-data"
    assert not manager.proxy_path(42).with_suffix(".part.mp4").exists()


@pytest.mark.asyncio
async def test_cancel_active_proxy_terminates_process_and_removes_partial_files(tmp_path):
    manager = RecordingPlaybackManager()
    manager.proxy_dir = tmp_path / "proxies"
    manager.proxy_dir.mkdir(parents=True)
    partial = manager.live_temp_path(88)
    partial.write_bytes(b"partial")
    manager._live_ids.add(88)
    manager._start_progress(88, 600, "live")

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    process = FakeProcess()
    manager._processes[88] = process

    result = await manager.cancel(88)

    assert result == {"cancelled": True, "state": "cancelled"}
    assert process.terminated is True
    assert not partial.exists()
    assert 88 not in manager._progress
    assert 88 not in manager._errors


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
