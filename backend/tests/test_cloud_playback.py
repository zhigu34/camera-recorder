import asyncio
import os
import time

import pytest

from app.services.cloud_playback import CloudPlaybackManager
from app.services.system_settings import RuntimeSettings


@pytest.mark.asyncio
async def test_cloud_restore_is_atomic_and_cached(monkeypatch, tmp_path):
    manager = CloudPlaybackManager()
    manager.cache_dir = tmp_path / "cloud-playback"

    class FakeProvider:
        def __init__(self, runtime):
            self.configured = True

        async def download(self, remote_path, target):
            assert remote_path == "监控录像/cam/2026-09-11/test.mp4"
            target.write_bytes(b"remote-video")

    monkeypatch.setattr("app.services.cloud_playback.OpenListWebDAVProvider", FakeProvider)

    state = await manager.start(
        42,
        "监控录像/cam/2026-09-11/test.mp4",
        RuntimeSettings(webdav_password="secret"),
    )
    assert state["state"] == "downloading"

    for _ in range(100):
        if manager.status(42)["state"] == "ready":
            break
        await asyncio.sleep(0.01)

    assert manager.status(42)["state"] == "ready"
    assert manager.source_path(42).read_bytes() == b"remote-video"
    assert not manager.temp_path(42).exists()


@pytest.mark.asyncio
async def test_cloud_restore_failure_does_not_leave_partial_file(monkeypatch, tmp_path):
    manager = CloudPlaybackManager()
    manager.cache_dir = tmp_path / "cloud-playback"

    class FakeProvider:
        def __init__(self, runtime):
            self.configured = True

        async def download(self, remote_path, target):
            target.write_bytes(b"partial")
            raise RuntimeError("remote unavailable")

    monkeypatch.setattr("app.services.cloud_playback.OpenListWebDAVProvider", FakeProvider)

    await manager.start(7, "remote.mp4", RuntimeSettings(webdav_password="secret"))
    for _ in range(100):
        if manager.status(7)["state"] == "error":
            break
        await asyncio.sleep(0.01)

    state = manager.status(7)
    assert state["state"] == "error"
    assert "remote unavailable" in state["error"]
    assert not manager.source_path(7).exists()
    assert not manager.temp_path(7).exists()


def test_old_cloud_playback_cache_is_removed(tmp_path):
    manager = CloudPlaybackManager()
    manager.cache_dir = tmp_path
    old = manager.source_path(1)
    recent = manager.source_path(2)
    old.write_bytes(b"old")
    recent.write_bytes(b"recent")
    stale = time.time() - (25 * 3600)
    os.utime(old, (stale, stale))

    manager._cleanup_old_sync()

    assert not old.exists()
    assert recent.exists()
