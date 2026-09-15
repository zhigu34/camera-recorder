import pytest
from pydantic import ValidationError

from app.schemas.camera import CameraCreate, CameraUpdate


def camera_payload(**overrides):
    payload = {
        "name": "gate",
        "ip": "10.0.0.10",
        "username": "admin",
        "password": "secret",
        "rtsp_path": "/main",
    }
    payload.update(overrides)
    return payload


def test_camera_create_defaults_to_manual_rtsp() -> None:
    value = CameraCreate(**camera_payload())
    assert value.connection_type == "manual_rtsp"


def test_camera_create_rejects_unimplemented_onvif() -> None:
    with pytest.raises(ValidationError):
        CameraCreate(**camera_payload(connection_type="onvif"))


def test_camera_update_rejects_unimplemented_onvif() -> None:
    with pytest.raises(ValidationError):
        CameraUpdate(connection_type="onvif")
