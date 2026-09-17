from types import SimpleNamespace

import pytest

from app.core.security import encrypt_secret
from app.services.hik_media_adapter import HikMediaAdapter
from app.services.media_adapter import resolve_media_source


def legacy_camera(**overrides):
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
        "connection": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def canonical_camera(**connection_overrides):
    connection_values = {
        "adapter": "hik_sdk",
        "hik_config": SimpleNamespace(
            sdk_port=9000,
            channel=3,
            main_stream_type=0,
            sub_stream_type=1,
        ),
    }
    connection_values.update(connection_overrides)
    return SimpleNamespace(
        id=8,
        connection_type="manual_rtsp",
        ip="10.0.0.8",
        username="legacy",
        password_encrypted=encrypt_secret("legacy-secret"),
        hik_metadata=None,
        connection=SimpleNamespace(**connection_values),
    )


def test_recording_uses_hik_main_stream_through_backend_internal_proxy() -> None:
    source = HikMediaAdapter().resolve_media_source(legacy_camera(), "recording")
    assert source.adapter == "hik_sdk"
    assert source.transport == "hik_bridge"
    assert source.role == "main"
    assert source.uri == "http://127.0.0.1:8000/internal/hik-media/7/main"
    assert source.bridge_target is None
    assert "super-secret" not in repr(source)


def test_preview_and_detection_use_hik_sub_stream_by_default() -> None:
    adapter = HikMediaAdapter()
    for purpose in ("preview", "detection"):
        source = adapter.resolve_media_source(legacy_camera(), purpose)
        assert source.role == "sub"
        assert source.uri.endswith("/7/sub")


def test_hik_preferred_main_and_sub_are_explicit() -> None:
    adapter = HikMediaAdapter()
    assert adapter.resolve_media_source(legacy_camera(), "preview", preferred="main").uri.endswith(
        "/7/main"
    )
    assert adapter.resolve_media_source(legacy_camera(), "preview", preferred="sub").uri.endswith(
        "/7/sub"
    )


def test_canonical_hik_connection_does_not_require_legacy_metadata() -> None:
    source = HikMediaAdapter().resolve_media_source(canonical_camera(), "recording")

    assert source.role == "main"
    assert source.uri.endswith("/8/main")


def test_current_hik_connection_without_config_does_not_fall_back_to_legacy_metadata() -> None:
    camera = canonical_camera(hik_config=None)
    camera.hik_metadata = SimpleNamespace(channel=1)

    with pytest.raises(ValueError, match="HIK current connection config is missing"):
        HikMediaAdapter().resolve_media_source(camera, "recording")


def test_current_non_hik_connection_is_rejected() -> None:
    with pytest.raises(ValueError, match="current connection adapter is onvif, expected hik_sdk"):
        HikMediaAdapter().resolve_media_source(canonical_camera(adapter="onvif"), "recording")


def test_legacy_metadata_is_required_without_current_connection() -> None:
    with pytest.raises(ValueError, match="HIK SDK metadata is missing"):
        HikMediaAdapter().resolve_media_source(legacy_camera(hik_metadata=None), "recording")


def test_default_registry_selects_hik_adapter() -> None:
    source = resolve_media_source(legacy_camera(), "recording")
    assert source.adapter == "hik_sdk"
