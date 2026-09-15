import pytest
from pydantic import ValidationError

from app.schemas.camera import CameraCreate, CameraUpdate, OnvifCameraCreate, OnvifProbeRequest


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


def test_generic_camera_create_still_rejects_onvif() -> None:
    with pytest.raises(ValidationError):
        CameraCreate(**camera_payload(connection_type="onvif"))


def test_generic_camera_update_still_rejects_switching_to_onvif() -> None:
    with pytest.raises(ValidationError):
        CameraUpdate(connection_type="onvif")


def test_onvif_probe_request_has_device_service_defaults() -> None:
    value = OnvifProbeRequest(host="10.0.0.20", username="admin", password="secret")
    assert value.port == 80
    assert value.device_service_url == "http://10.0.0.20:80/onvif/device_service"


def test_onvif_camera_create_carries_normal_camera_policy() -> None:
    value = OnvifCameraCreate(
        name="front-door-onvif",
        host="10.0.0.20",
        port=8000,
        username="operator",
        password="secret",
        enabled=True,
        auto_record=True,
        timestamp_mode="reconstruct",
    )
    assert value.name == "front-door-onvif"
    assert value.connection_type == "onvif"
    assert value.device_service_url == "http://10.0.0.20:8000/onvif/device_service"
    assert value.auto_record is True
