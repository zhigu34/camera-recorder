from pathlib import Path

from app.core.config import settings
from app.models.recording import Recording
from app.services.upload_manager import OpenListWebDAVProvider, UploadManager


def test_remote_path_preserves_camera_date_hierarchy(monkeypatch, tmp_path: Path):
    recordings_dir = tmp_path / "recordings"
    monkeypatch.setattr(settings, "recordings_dir", recordings_dir)
    monkeypatch.setattr(settings, "webdav_root", "监控录像")

    recording = Recording(
        camera_id=1,
        mp4_path=str(
            recordings_dir
            / "监控-大厅"
            / "2026-09-11"
            / "监控-大厅_2026-09-11_12-00-00.mp4"
        ),
    )

    manager = UploadManager()
    assert manager.remote_path_for(recording) == (
        "监控录像/监控-大厅/2026-09-11/监控-大厅_2026-09-11_12-00-00.mp4"
    )


def test_webdav_url_percent_encodes_remote_path(monkeypatch):
    monkeypatch.setattr(settings, "webdav_url", "http://openlist:5244/dav/115")
    provider = OpenListWebDAVProvider()
    url = provider._url("监控录像/监控-大厅/test file.mp4")

    assert url.startswith("http://openlist:5244/dav/115/")
    assert "%E7%9B%91%E6%8E%A7%E5%BD%95%E5%83%8F" in url
    assert "test%20file.mp4" in url
