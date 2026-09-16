import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Camera, CameraConnection, RtspConnectionConfig


def _camera(name: str = "gate") -> Camera:
    return Camera(
        name=name,
        connection_type="manual_rtsp",
        ip="10.0.0.10",
        rtsp_port=554,
        username="admin",
        password_encrypted="ciphertext",
        rtsp_path="/main",
        sub_rtsp_path="/sub",
    )


def _connection(camera: Camera, host: str = "10.0.0.10") -> CameraConnection:
    connection = CameraConnection(
        camera=camera,
        adapter="manual_rtsp",
        host=host,
        username="admin",
        password_encrypted="ciphertext",
    )
    connection.rtsp_config = RtspConnectionConfig(
        port=554,
        main_path="/main",
        sub_path="/sub",
    )
    return connection


def test_camera_connection_round_trips_rtsp_config_and_defaults() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

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
        assert camera.connection.adapter == "manual_rtsp"
        assert camera.connection.host == "10.0.0.10"
        assert camera.connection.username == "admin"
        assert camera.connection.password_encrypted == "ciphertext"
        assert camera.connection.revision == 1
        assert camera.connection.verification_status == "unverified"
        assert camera.connection.rtsp_config is not None
        assert camera.connection.rtsp_config.port == 554
        assert camera.connection.rtsp_config.main_path == "/main"
        assert camera.connection.rtsp_config.sub_path == "/sub"


def test_camera_allows_only_one_current_connection() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        camera = _camera()
        session.add(camera)
        session.flush()
        session.add(_connection(camera, "10.0.0.10"))
        session.commit()

        session.add(_connection(camera, "10.0.0.11"))
        with pytest.raises(IntegrityError):
            session.commit()
