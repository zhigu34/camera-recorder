from datetime import datetime, timezone

from app.core.security import encrypt_secret
from app.models import Camera
from app.services.camera_connection import upsert_hik_connection, upsert_onvif_connection


def _camera(name: str) -> Camera:
    return Camera(
        name=name,
        connection_type="manual_rtsp",
        ip="192.0.2.1",
        rtsp_port=554,
        username="admin",
        password_encrypted=encrypt_secret("legacy-secret"),
        rtsp_path="/main",
    )


def test_onvif_connection_can_be_saved_unverified_without_discovery_cache() -> None:
    camera = _camera("unverified-onvif")

    connection = upsert_onvif_connection(
        camera,
        host="192.0.2.20",
        username="admin",
        password_encrypted=encrypt_secret("secret"),
        device_service_url="http://192.0.2.20:80/onvif/device_service",
        verification_status="unverified",
    )

    assert connection.adapter == "onvif"
    assert connection.verification_status == "unverified"
    assert connection.verified_at is None
    assert connection.last_error is None
    assert connection.onvif_config is not None
    assert connection.onvif_config.recording_profile_token is None
    assert connection.onvif_config.recording_uri is None
    assert camera.connection_type == "onvif"
    assert camera.ip == "192.0.2.20"
    assert camera.username == "admin"


def test_hik_connection_can_be_saved_unverified_without_discovered_metadata() -> None:
    camera = _camera("unverified-hik")

    connection = upsert_hik_connection(
        camera,
        host="192.0.2.30",
        username="admin",
        password_encrypted=encrypt_secret("secret"),
        sdk_port=8000,
        channel=1,
        main_stream_type=0,
        sub_stream_type=1,
        verification_status="unverified",
    )

    assert connection.adapter == "hik_sdk"
    assert connection.verification_status == "unverified"
    assert connection.verified_at is None
    assert connection.last_error is None
    assert connection.hik_config is not None
    assert connection.hik_config.device_serial is None
    assert connection.hik_config.device_model is None
    assert connection.hik_config.device_name is None
    assert camera.connection_type == "hik_sdk"
    assert camera.ip == "192.0.2.30"
    assert camera.username == "admin"


def test_onvif_noop_unverified_write_preserves_verified_cache_and_revision() -> None:
    camera = _camera("verified-onvif")
    verified_at = datetime(2026, 9, 17, 1, 2, 3, tzinfo=timezone.utc)
    password_encrypted = encrypt_secret("secret")
    connection = upsert_onvif_connection(
        camera,
        host="192.0.2.20",
        username="admin",
        password_encrypted=password_encrypted,
        device_service_url="http://192.0.2.20:80/onvif/device_service",
        device_uuid="uuid-20",
        capabilities={"media": "http://192.0.2.20/onvif/media"},
        profiles=[{"token": "main"}],
        recording_profile_token="main",
        preview_profile_token="main",
        detection_profile_token="main",
        recording_uri="rtsp://192.0.2.20/main",
        preview_uri="rtsp://192.0.2.20/main",
        detection_uri="rtsp://192.0.2.20/main",
        verified_at=verified_at,
        verification_status="verified",
    )
    before_revision = connection.revision

    same = upsert_onvif_connection(
        camera,
        host="192.0.2.20",
        username="admin",
        password_encrypted=encrypt_secret("secret"),
        device_service_url="http://192.0.2.20:80/onvif/device_service",
        verification_status="unverified",
    )

    assert same.revision == before_revision
    assert same.verification_status == "verified"
    assert same.verified_at == verified_at
    assert same.onvif_config is not None
    assert same.onvif_config.device_uuid == "uuid-20"
    assert same.onvif_config.recording_profile_token == "main"
    assert same.onvif_config.recording_uri == "rtsp://192.0.2.20/main"


def test_hik_noop_unverified_write_preserves_verified_metadata_and_revision() -> None:
    camera = _camera("verified-hik")
    verified_at = datetime(2026, 9, 17, 1, 2, 3, tzinfo=timezone.utc)
    connection = upsert_hik_connection(
        camera,
        host="192.0.2.30",
        username="admin",
        password_encrypted=encrypt_secret("secret"),
        sdk_port=8000,
        channel=1,
        main_stream_type=0,
        sub_stream_type=1,
        device_serial="SERIAL-30",
        device_model="DS-TEST",
        device_name="Gate",
        verified_at=verified_at,
        verification_status="verified",
    )
    before_revision = connection.revision

    same = upsert_hik_connection(
        camera,
        host="192.0.2.30",
        username="admin",
        password_encrypted=encrypt_secret("secret"),
        sdk_port=8000,
        channel=1,
        main_stream_type=0,
        sub_stream_type=1,
        verification_status="unverified",
    )

    assert same.revision == before_revision
    assert same.verification_status == "verified"
    assert same.verified_at == verified_at
    assert same.hik_config is not None
    assert same.hik_config.device_serial == "SERIAL-30"
    assert same.hik_config.device_model == "DS-TEST"
    assert same.hik_config.device_name == "Gate"
