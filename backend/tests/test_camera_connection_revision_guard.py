from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from app.services import camera_config as camera_config_module
from app.services import motion_manager as motion_manager_module
from app.services.motion_worker import MotionWorkerConfig


class _DbContext:
    def __init__(self, camera=None, motion=None, *, error: Exception | None = None) -> None:
        self.camera = camera
        self.motion = motion
        self.error = error

    async def __aenter__(self):
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, _key):
        name = getattr(model, "__name__", "")
        if name == "Camera":
            return self.camera
        if name == "MotionDetectionSettings":
            return self.motion
        return None

    async def scalars(self, _statement):
        return []


def _camera(*, revision: int | None = 7, enabled: bool = True):
    connection = None if revision is None else SimpleNamespace(revision=revision)
    return SimpleNamespace(
        id=21,
        name="Front Door",
        enabled=enabled,
        connection=connection,
        timestamp_mode="wallclock",
        fps_num=25,
        fps_den=1,
        audio_codec=None,
        sample_rate=None,
        audio_frame_samples=None,
        ip="192.0.2.21",
        rtsp_port=554,
        username="admin",
        password_encrypted="ciphertext",
        rtsp_path="/main",
        sub_rtsp_path="/sub",
    )


def _revision_module():
    return importlib.import_module("app.services.camera_connection_revision")


@pytest.mark.asyncio
async def test_revision_checker_reports_current_and_stale(monkeypatch) -> None:
    module = _revision_module()
    camera = _camera(revision=7)
    monkeypatch.setattr(module, "SessionLocal", lambda: _DbContext(camera=camera))

    assert await module.connection_revision_state(21, None) == "current"
    assert await module.connection_revision_state(21, 7) == "current"
    assert await module.connection_revision_state(21, 8) == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("camera", "expected_revision"),
    [
        (None, 7),
        (_camera(revision=7, enabled=False), 7),
        (_camera(revision=None), 7),
    ],
)
async def test_revision_checker_treats_missing_disabled_or_connectionless_camera_as_stale(
    monkeypatch,
    camera,
    expected_revision: int,
) -> None:
    module = _revision_module()
    monkeypatch.setattr(module, "SessionLocal", lambda: _DbContext(camera=camera))

    assert await module.connection_revision_state(21, expected_revision) == "stale"


@pytest.mark.asyncio
async def test_revision_checker_reports_unknown_on_lookup_failure(monkeypatch) -> None:
    module = _revision_module()
    monkeypatch.setattr(
        module,
        "SessionLocal",
        lambda: _DbContext(error=RuntimeError("database unavailable")),
    )

    assert await module.connection_revision_state(21, 7) == "unknown"


def test_recording_runtime_config_captures_connection_revision(monkeypatch) -> None:
    camera = _camera(revision=9)
    monkeypatch.setattr(
        camera_config_module,
        "resolve_media_source",
        lambda _camera, _role: SimpleNamespace(uri="rtsp://camera/main"),
    )

    config = camera_config_module.runtime_config(camera)

    assert config.connection_revision == 9


def test_motion_worker_config_accepts_connection_revision() -> None:
    config = MotionWorkerConfig(
        camera_id=21,
        ip="192.0.2.21",
        port=554,
        username="admin",
        password="secret",
        main_path="/main",
        sub_path="/sub",
        rtsp_timeout_us=3_000_000,
        analysis_fps=5,
        analysis_width=640,
        sensitivity="medium",
        min_duration_ms=500,
        merge_gap_ms=1000,
        zones=[],
        connection_revision=11,
    )

    assert config.connection_revision == 11


@pytest.mark.asyncio
async def test_motion_config_loader_captures_connection_revision(monkeypatch) -> None:
    camera = _camera(revision=12)
    motion = SimpleNamespace(
        enabled=True,
        analysis_fps=5,
        analysis_width=640,
        sensitivity="medium",
        min_duration_ms=500,
        merge_gap_ms=1000,
        event_min_interval_ms=60_000,
    )
    monkeypatch.setattr(
        motion_manager_module,
        "SessionLocal",
        lambda: _DbContext(camera=camera, motion=motion),
    )
    monkeypatch.setattr(
        motion_manager_module,
        "load_runtime_settings",
        lambda _db: _async_value(SimpleNamespace(rtsp_timeout_us=3_000_000)),
    )
    monkeypatch.setattr(motion_manager_module, "decrypt_secret", lambda _value: "secret")
    monkeypatch.setattr(
        motion_manager_module,
        "resolve_stream",
        lambda _camera, _role: SimpleNamespace(uri="rtsp://camera/sub", role="sub"),
    )

    config = await motion_manager_module._default_config_loader(21)

    assert config is not None
    assert config.connection_revision == 12


async def _async_value(value):
    return value
