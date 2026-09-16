from types import SimpleNamespace

import pytest

from app.core.security import encrypt_secret
from app.services.hik_media_adapter import HikMediaAdapter
from app.services.media_adapter import resolve_media_source


def camera(**overrides):
    values = {
        "id": 7,
        "connection_type": "hik_sdk",
        "ip": "10.0.0.8",
        "username": "admin",
        "password_encrypted": encrypt_secret("super-secret"),
        "hik_metadata": SimpleNamespace(
            sdk_port=8000,
            channel=2,
            main_stream_type=0,
            sub_stream_type=1,
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_recording_uses_hik_main_stream_through_backend_internal_proxy() -> None:
    source = HikMediaAdapter().resolve_media_source(camera(), "recording")
    assert source.adapter == "hik_sdk"
    assert source.transport == "hik_bridge"
    assert source.role == "main"
    assert source.uri == "http://127.0.0.1:8000/internal/hik-media/7/main"
    assert source.bridge_target is None
    assert "super-secret" not in repr(source)


def test_preview_and_detection_use_hik_sub_stream_by_default() -> None:
    adapter = HikMediaAdapter()
    for purpose in ("preview", "detection"):
        source = adapter.resolve_media_source(camera(), purpose)
        assert source.role == "sub"
        assert source.uri.endswith("/7/sub")


def test_hik_preferred_main_and_sub_are_explicit() -> None:
    adapter = HikMediaAdapter()
    assert adapter.resolve_media_source(camera(), "preview", preferred="main").uri.endswith("/7/main")
    assert adapter.resolve_media_source(camera(), "preview", preferred="sub").uri.endswith("/7/sub")


def test_hik_metadata_is_required_and_never_falls_back_to_rtsp() -> None:
    with pytest.raises(ValueError, match="HIK SDK metadata is missing"):
        HikMediaAdapter().resolve_media_source(camera(hik_metadata=None), "recording")


def test_default_registry_selects_hik_adapter() -> None:
    source = resolve_media_source(camera(), "recording")
    assert source.adapter == "hik_sdk"
