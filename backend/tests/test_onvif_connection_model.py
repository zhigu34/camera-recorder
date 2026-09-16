import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Camera, CameraConnection, OnvifConnectionConfig


def _engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        if isinstance(dbapi_connection, sqlite3.Connection):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def _camera() -> Camera:
    return Camera(
        name="onvif-current-connection",
        connection_type="onvif",
        ip="10.0.0.20",
        rtsp_port=554,
        username="operator",
        password_encrypted="ciphertext",
        rtsp_path="/main",
        sub_rtsp_path="/sub",
    )


def _connection(camera: Camera) -> CameraConnection:
    connection = CameraConnection(
        camera=camera,
        adapter="onvif",
        host="10.0.0.20",
        username="operator",
        password_encrypted="ciphertext",
        verification_status="verified",
    )
    connection.onvif_config = OnvifConnectionConfig(
        device_service_url="http://10.0.0.20:80/onvif/device_service",
        device_uuid="urn:uuid:camera-20",
        capabilities_json={"media_xaddr": "http://10.0.0.20/onvif/media_service"},
        profiles_json=[{"token": "main"}, {"token": "sub"}],
        recording_profile_token="main",
        preview_profile_token="sub",
        detection_profile_token="sub",
        recording_uri="rtsp://10.0.0.20:554/main",
        preview_uri="rtsp://10.0.0.20:554/sub",
        detection_uri="rtsp://10.0.0.20:554/sub",
    )
    return connection


def test_onvif_connection_config_round_trips_connection_scoped_state() -> None:
    engine = _engine()

    with Session(engine) as session:
        camera = _camera()
        camera.connection = _connection(camera)
        session.add(camera)
        session.commit()
        camera_id = camera.id

    with Session(engine) as session:
        camera = session.get(Camera, camera_id)
        assert camera is not None
        assert camera.connection is not None
        assert camera.connection.adapter == "onvif"
        assert camera.connection.onvif_config is not None
        config = camera.connection.onvif_config
        assert config.device_service_url == "http://10.0.0.20:80/onvif/device_service"
        assert config.device_uuid == "urn:uuid:camera-20"
        assert config.capabilities_json["media_xaddr"].endswith("/onvif/media_service")
        assert [item["token"] for item in config.profiles_json] == ["main", "sub"]
        assert config.recording_profile_token == "main"
        assert config.preview_profile_token == "sub"
        assert config.detection_profile_token == "sub"
        assert config.recording_uri == "rtsp://10.0.0.20:554/main"
        assert config.preview_uri == "rtsp://10.0.0.20:554/sub"
        assert config.detection_uri == "rtsp://10.0.0.20:554/sub"


def test_deleting_current_connection_cascades_only_its_onvif_config() -> None:
    engine = _engine()

    with Session(engine) as session:
        camera = _camera()
        camera.connection = _connection(camera)
        session.add(camera)
        session.commit()
        camera_id = camera.id
        connection_id = camera.connection.id

        session.delete(camera.connection)
        session.commit()

        assert session.get(Camera, camera_id) is not None
        assert session.get(CameraConnection, connection_id) is None
        assert session.get(OnvifConnectionConfig, connection_id) is None
