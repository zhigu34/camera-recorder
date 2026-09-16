from app.models.hikvision import HikDeviceMetadata
from app.schemas.hikvision import HikCameraCreate, HikProbeRequest


def test_hik_metadata_keeps_adapter_specific_fields_only() -> None:
    columns = HikDeviceMetadata.__table__.columns
    assert set(columns.keys()) >= {
        "camera_id",
        "sdk_port",
        "channel",
        "main_stream_type",
        "sub_stream_type",
        "device_serial",
        "device_model",
        "device_name",
    }
    assert "password" not in columns
    assert "password_encrypted" not in columns


def test_hik_probe_defaults_to_sdk_port_and_channel() -> None:
    payload = HikProbeRequest(host="10.0.0.8", password="secret")
    assert payload.port == 8000
    assert payload.channel == 1
    assert payload.username == "admin"


def test_hik_create_is_pinned_to_hik_sdk_connection_type() -> None:
    payload = HikCameraCreate(name="gate", host="10.0.0.8", password="secret")
    assert payload.connection_type == "hik_sdk"
