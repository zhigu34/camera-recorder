from types import SimpleNamespace

import pytest

from app.core.security import encrypt_secret
from app.services.stream_resolver import UnsupportedDeviceAdapter, resolve_stream


def camera(**overrides):
    values = {
        "connection_type": "manual_rtsp",
        "ip": "10.0.0.10",
        "rtsp_port": 554,
        "username": "admin",
        "password_encrypted": encrypt_secret("secret"),
        "rtsp_path": "/ch1/main",
        "sub_rtsp_path": "/ch1/sub",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_recording_uses_main_stream() -> None:
    value = resolve_stream(camera(), "recording")
    assert value.role == "main"
    assert value.uri.endswith("/ch1/main")


def test_detection_prefers_sub_stream() -> None:
    value = resolve_stream(camera(), "detection")
    assert value.role == "sub"
    assert value.uri.endswith("/ch1/sub")


def test_detection_infers_common_sub_stream() -> None:
    value = resolve_stream(camera(sub_rtsp_path=None), "detection")
    assert value.role == "sub"
    assert value.uri.endswith("/ch1/sub")


def test_detection_falls_back_to_main_when_sub_cannot_be_inferred() -> None:
    value = resolve_stream(camera(rtsp_path="/stream", sub_rtsp_path=None), "detection")
    assert value.role == "main"
    assert value.uri.endswith("/stream")


def test_preview_honors_explicit_main_and_sub() -> None:
    assert resolve_stream(camera(), "preview", preferred="main").role == "main"
    assert resolve_stream(camera(), "preview", preferred="sub").role == "sub"


def test_preview_auto_prefers_sub() -> None:
    assert resolve_stream(camera(), "preview", preferred="auto").role == "sub"


def test_unimplemented_onvif_never_falls_back_to_manual() -> None:
    with pytest.raises(UnsupportedDeviceAdapter):
        resolve_stream(camera(connection_type="onvif"), "preview")
