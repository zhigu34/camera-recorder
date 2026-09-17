from datetime import datetime, timezone

import pytest

from app.core.security import encrypt_secret
from app.models import Camera, CameraConnection
from app.services import camera_connection as connection_service


def _camera() -> Camera:
    return Camera(
        name="hik-current-write",
        connection_type="hik_sdk",
        ip="192.0.2.70",
        rtsp_port=554,
        username="legacy",
        password_encrypted=encrypt_secret("legacy-secret"),
        rtsp_path="/hik-sdk/main",
        sub_rtsp_path="/hik-sdk/sub",
    )


def _upsert(camera: Camera, **overrides):
    assert hasattr(connection_service, "upsert_hik_connection")
    values = {
        "host": "192.0.2.71",
        "username": "admin",
        "password_encrypted": encrypt_secret("current-secret"),
        "sdk_port": 8000,
        "channel": 2,
        "main_stream_type": 0,
        "sub_stream_type": 1,
        "device_serial": "HIK-71",
        "device_model": "DS-2CD-Test",
        "device_name": "Front Gate",
        "verified_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return connection_service.upsert_hik_connection(camera, **values)


def test_hik_upsert_creates_canonical_connection_and_rollback_shadow() -> None:
    camera = _camera()

    connection = _upsert(camera)

    assert camera.connection is connection
    assert connection.adapter == "hik_sdk"
    assert connection.revision == 1
    assert connection.verification_status == "verified"
    assert connection.hik_config is not None
    assert connection.hik_config.sdk_port == 8000
    assert connection.hik_config.channel == 2
    assert connection.hik_config.device_serial == "HIK-71"
    assert camera.connection_type == "hik_sdk"
    assert camera.ip == "192.0.2.71"
    assert camera.rtsp_port == 554
    assert camera.username == "admin"
    assert camera.rtsp_path == "/hik-sdk/main"
    assert camera.sub_rtsp_path == "/hik-sdk/sub"
    assert camera.hik_metadata is not None
    assert camera.hik_metadata.channel == 2
    assert camera.hik_metadata.device_serial == "HIK-71"


def test_hik_upsert_reuses_connection_and_increments_revision_for_config_change() -> None:
    camera = _camera()
    connection = _upsert(camera)
    original = connection

    updated = _upsert(
        camera,
        host="192.0.2.72",
        username="operator",
        password_encrypted=encrypt_secret("updated-secret"),
        channel=3,
        device_serial="HIK-72",
        device_model="DS-2CD-Updated",
    )

    assert updated is original
    assert updated.revision == 2
    assert updated.host == "192.0.2.72"
    assert updated.username == "operator"
    assert updated.hik_config is not None
    assert updated.hik_config.channel == 3
    assert updated.hik_config.device_serial == "HIK-72"
    assert camera.hik_metadata is not None
    assert camera.hik_metadata.channel == 3


def test_hik_upsert_same_plaintext_password_preserves_ciphertext_and_revision() -> None:
    camera = _camera()
    first_ciphertext = encrypt_secret("stable-secret")
    _upsert(camera, password_encrypted=first_ciphertext)

    updated = _upsert(camera, password_encrypted=encrypt_secret("stable-secret"))

    assert updated.revision == 1
    assert updated.password_encrypted == first_ciphertext
    assert camera.password_encrypted == first_ciphertext


def test_hik_upsert_rejects_different_current_adapter() -> None:
    camera = _camera()
    camera.connection = CameraConnection(
        adapter="onvif",
        host="192.0.2.80",
        username="viewer",
        password_encrypted=encrypt_secret("onvif-secret"),
        revision=4,
    )

    with pytest.raises(connection_service.ConnectionAdapterMismatch):
        _upsert(camera)

    assert camera.connection.adapter == "onvif"
    assert camera.connection.revision == 4
    assert camera.ip == "192.0.2.70"
