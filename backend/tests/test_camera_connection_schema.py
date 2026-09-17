from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.security import encrypt_secret
from app.models import Camera, CameraConnection, HikConnectionConfig, OnvifConnectionConfig, RtspConnectionConfig


def _schema_types():
    from app.schemas.camera_connection import CameraConnectionCreate, CameraConnectionUpdate

    return CameraConnectionCreate, CameraConnectionUpdate


def test_connection_create_uses_adapter_discriminator_for_all_supported_adapters() -> None:
    CameraConnectionCreate, _ = _schema_types()
    adapter = TypeAdapter(CameraConnectionCreate)

    manual = adapter.validate_python(
        {
            "adapter": "manual_rtsp",
            "host": "192.0.2.10",
            "username": "admin",
            "password": "manual-secret",
            "port": 8554,
            "main_path": "/main",
            "sub_path": "/sub",
        }
    )
    onvif = adapter.validate_python(
        {
            "adapter": "onvif",
            "host": "192.0.2.20",
            "username": "operator",
            "password": "onvif-secret",
            "port": 8080,
        }
    )
    hik = adapter.validate_python(
        {
            "adapter": "hik_sdk",
            "host": "192.0.2.30",
            "username": "viewer",
            "password": "hik-secret",
            "sdk_port": 9000,
            "channel": 2,
            "main_stream_type": 0,
            "sub_stream_type": 1,
        }
    )

    assert manual.adapter == "manual_rtsp"
    assert manual.port == 8554
    assert manual.main_path == "/main"
    assert onvif.adapter == "onvif"
    assert onvif.port == 8080
    assert hik.adapter == "hik_sdk"
    assert hik.sdk_port == 9000
    assert hik.channel == 2


def test_connection_create_requires_password_but_update_can_keep_existing_password() -> None:
    CameraConnectionCreate, CameraConnectionUpdate = _schema_types()
    create_adapter = TypeAdapter(CameraConnectionCreate)
    update_adapter = TypeAdapter(CameraConnectionUpdate)

    with pytest.raises(ValidationError):
        create_adapter.validate_python(
            {
                "adapter": "onvif",
                "host": "192.0.2.20",
                "username": "admin",
                "port": 80,
            }
        )

    update = update_adapter.validate_python(
        {
            "adapter": "onvif",
            "host": "192.0.2.20",
            "username": "admin",
            "port": 80,
        }
    )
    assert update.password is None


def test_connection_schema_rejects_adapter_specific_fields_from_other_adapters() -> None:
    CameraConnectionCreate, _ = _schema_types()
    adapter = TypeAdapter(CameraConnectionCreate)

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "adapter": "onvif",
                "host": "192.0.2.20",
                "username": "admin",
                "password": "secret",
                "port": 80,
                "main_path": "/must-not-be-accepted",
            }
        )

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "adapter": "manual_rtsp",
                "host": "192.0.2.10",
                "username": "admin",
                "password": "secret",
                "main_path": "/main",
                "channel": 2,
            }
        )


def test_connection_schema_rejects_url_or_path_in_host() -> None:
    CameraConnectionCreate, _ = _schema_types()
    adapter = TypeAdapter(CameraConnectionCreate)

    for bad_host in ("rtsp://192.0.2.10", "192.0.2.10/path", " https://camera.local "):
        with pytest.raises(ValidationError):
            adapter.validate_python(
                {
                    "adapter": "manual_rtsp",
                    "host": bad_host,
                    "username": "admin",
                    "password": "secret",
                    "main_path": "/main",
                }
            )


def _camera_with_connection(adapter: str) -> Camera:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    camera = Camera(
        id=12,
        name=f"schema-{adapter}",
        manufacturer="Acme",
        model="Model 1",
        form_factor="bullet",
        connection_type=adapter,
        ip="192.0.2.12",
        rtsp_port=554,
        username="admin",
        password_encrypted=encrypt_secret("legacy-secret"),
        rtsp_path="/legacy-main",
        enabled=True,
        auto_record=False,
        recording_schedule_enabled=False,
        recording_schedule=[],
        timestamp_mode="reconstruct",
        status="unknown",
        created_at=now,
        updated_at=now,
    )
    connection = CameraConnection(
        id=77,
        adapter=adapter,
        host="192.0.2.12",
        username="admin",
        password_encrypted=encrypt_secret("connection-secret"),
        revision=4,
        verification_status="verified",
        verified_at=now,
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    if adapter == "manual_rtsp":
        connection.rtsp_config = RtspConnectionConfig(
            port=8554,
            main_path="/main",
            sub_path="/sub",
            created_at=now,
            updated_at=now,
        )
    elif adapter == "onvif":
        connection.onvif_config = OnvifConnectionConfig(
            device_service_url="http://192.0.2.12:8080/onvif/device_service",
            device_uuid="uuid-12",
            capabilities_json={"media": "supported"},
            profiles_json=[{"token": "main"}],
            recording_profile_token="main",
            preview_profile_token="main",
            detection_profile_token="main",
            recording_uri="rtsp://192.0.2.12/main",
            preview_uri="rtsp://192.0.2.12/main",
            detection_uri="rtsp://192.0.2.12/main",
            created_at=now,
            updated_at=now,
        )
    else:
        connection.hik_config = HikConnectionConfig(
            sdk_port=8000,
            channel=3,
            main_stream_type=0,
            sub_stream_type=1,
            device_serial="SERIAL-12",
            device_model="DS-TEST",
            device_name="East Gate",
            created_at=now,
            updated_at=now,
        )
    camera.connection = connection
    return camera


@pytest.mark.parametrize(
    ("adapter", "expected_config"),
    [
        (
            "manual_rtsp",
            {"port": 8554, "main_path": "/main", "sub_path": "/sub"},
        ),
        (
            "onvif",
            {
                "port": 8080,
                "device_service_url": "http://192.0.2.12:8080/onvif/device_service",
                "device_uuid": "uuid-12",
                "recording_profile_token": "main",
                "preview_profile_token": "main",
                "detection_profile_token": "main",
            },
        ),
        (
            "hik_sdk",
            {
                "sdk_port": 8000,
                "channel": 3,
                "main_stream_type": 0,
                "sub_stream_type": 1,
                "device_serial": "SERIAL-12",
                "device_model": "DS-TEST",
                "device_name": "East Gate",
            },
        ),
    ],
)
def test_camera_read_projects_canonical_connection_without_credentials(
    adapter: str,
    expected_config: dict,
) -> None:
    from app.schemas.camera import CameraRead

    read = CameraRead.model_validate(_camera_with_connection(adapter))
    assert read.connection is not None
    assert read.connection.id == 77
    assert read.connection.adapter == adapter
    assert read.connection.host == "192.0.2.12"
    assert read.connection.username == "admin"
    assert read.connection.password_set is True
    assert read.connection.revision == 4
    assert read.connection.verification_status == "verified"
    assert read.connection.config.model_dump(exclude_none=True) == expected_config

    dumped = read.model_dump()
    assert "password" not in dumped["connection"]
    assert "password_encrypted" not in dumped["connection"]
