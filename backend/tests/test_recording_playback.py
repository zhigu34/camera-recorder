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

    state = await manager.start(42, source, "hevc")
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
