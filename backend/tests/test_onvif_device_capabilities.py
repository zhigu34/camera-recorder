from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import encrypt_secret
from app.models import Camera, CameraConnection, OnvifConnectionConfig
from app.schemas.camera import CameraRead
from app.services.camera_adapter_probe import CameraConnectionProbeResult, apply_probe_success


def _engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        if isinstance(dbapi_connection, sqlite3.Connection):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def _camera() -> Camera:
    camera = Camera(
        name="onvif-capability-details",
        connection_type="onvif",
        ip="192.0.2.44",
        rtsp_port=554,
        username="operator",
        password_encrypted=encrypt_secret("secret"),
        rtsp_path="/",
        enabled=False,
    )
    connection = CameraConnection(
        adapter="onvif",
        host="192.0.2.44",
        username="operator",
        password_encrypted=encrypt_secret("secret"),
        revision=1,
        verification_status="unverified",
    )
    connection.onvif_config = OnvifConnectionConfig(
        device_service_url="https://192.0.2.44:8443/custom/device",
        capabilities_json={},
        profiles_json=[],
    )
    camera.connection = connection
    return camera


def test_probe_success_persists_onvif_device_identity_and_capabilities() -> None:
    camera = _camera()
    result = CameraConnectionProbeResult(
        adapter="onvif",
        device={
            "manufacturer": "Example",
            "model": "IPC-4K",
            "firmware_version": "5.1.2",
            "serial_number": "SN-0044",
            "hardware_id": "HW-A1",
        },
        media={"video_codec": "h264", "width": 3840, "height": 2160},
        connection_cache={
            "device_uuid": "urn:uuid:camera-44",
            "capabilities": {
                "media_xaddr": "http://192.0.2.44/onvif/media",
                "events_xaddr": "http://192.0.2.44/onvif/events",
                "ptz_xaddr": None,
            },
            "profiles": [
                {
                    "token": "main",
                    "name": "Main",
                    "encoding": "H264",
                    "width": 3840,
                    "height": 2160,
                    "fps": 25.0,
                    "uri": "rtsp://viewer:secret@192.0.2.44:554/main",
                },
                {
                    "token": "sub",
                    "name": "Sub",
                    "encoding": "H264",
                    "width": 640,
                    "height": 360,
                    "fps": 12.0,
                    "uri": "rtsp://192.0.2.44:554/sub",
                },
            ],
            "recording_profile_token": "main",
            "preview_profile_token": "sub",
            "detection_profile_token": "sub",
            "recording_uri": "rtsp://192.0.2.44:554/main",
            "preview_uri": "rtsp://192.0.2.44:554/sub",
            "detection_uri": "rtsp://192.0.2.44:554/sub",
        },
    )

    apply_probe_success(camera, result, verified_at=datetime.now(timezone.utc))

    config = camera.connection.onvif_config
    assert config is not None
    assert config.firmware_version == "5.1.2"
    assert config.serial_number == "SN-0044"
    assert config.hardware_id == "HW-A1"
    assert config.capabilities_json["events_xaddr"].endswith("/onvif/events")
    assert [profile["token"] for profile in config.profiles_json] == ["main", "sub"]


def test_camera_read_exposes_sanitized_onvif_capability_details() -> None:
    camera = _camera()
    config = camera.connection.onvif_config
    assert config is not None
    config.device_uuid = "urn:uuid:camera-44"
    config.firmware_version = "5.1.2"
    config.serial_number = "SN-0044"
    config.hardware_id = "HW-A1"
    config.capabilities_json = {
        "media_xaddr": "http://192.0.2.44/onvif/media",
        "events_xaddr": "http://192.0.2.44/onvif/events",
        "ptz_xaddr": None,
    }
    config.profiles_json = [
        {
            "token": "main",
            "name": "Main",
            "encoding": "H264",
            "width": 3840,
            "height": 2160,
            "fps": 25.0,
            "uri": "rtsp://viewer:secret@192.0.2.44:554/main",
        }
    ]
    config.recording_profile_token = "main"
    config.preview_profile_token = "main"
    config.detection_profile_token = "main"

    engine = _engine()
    with Session(engine) as session:
        session.add(camera)
        session.commit()
        session.refresh(camera)

        payload = CameraRead.model_validate(camera).model_dump()

    onvif = payload["connection"]["config"]
    assert onvif["firmware_version"] == "5.1.2"
    assert onvif["serial_number"] == "SN-0044"
    assert onvif["hardware_id"] == "HW-A1"
    assert onvif["capabilities"]["events_xaddr"].endswith("/onvif/events")
    assert onvif["profiles"][0]["token"] == "main"
    assert onvif["profiles"][0]["uri"] == "rtsp://192.0.2.44:554/main"
    assert "viewer:secret@" not in str(onvif)
    assert "password" not in str(onvif).lower()
