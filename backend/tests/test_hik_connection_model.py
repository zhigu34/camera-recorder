from app.models.camera_connection import CameraConnection
import app.models.hikvision as hikvision


def test_hik_connection_config_is_keyed_by_current_connection() -> None:
    assert hasattr(hikvision, "HikConnectionConfig")
    config_type = hikvision.HikConnectionConfig
    columns = config_type.__table__.columns

    assert columns["connection_id"].primary_key is True
    assert set(columns.keys()) >= {
        "connection_id",
        "sdk_port",
        "channel",
        "main_stream_type",
        "sub_stream_type",
        "device_serial",
        "device_model",
        "device_name",
    }
    foreign_keys = {str(item.target_fullname) for item in columns["connection_id"].foreign_keys}
    assert foreign_keys == {"camera_connections.id"}


def test_camera_connection_owns_one_hik_config_with_delete_orphan() -> None:
    assert "hik_config" in CameraConnection.__mapper__.relationships
    relationship = CameraConnection.__mapper__.relationships["hik_config"]

    assert relationship.uselist is False
    assert relationship.mapper.class_ is hikvision.HikConnectionConfig
    assert relationship.cascade.delete_orphan is True
