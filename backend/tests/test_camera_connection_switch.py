from datetime import datetime, timezone

from app.core.security import encrypt_secret
from app.models import Camera, Recording
from app.services import camera_connection as connection_service

NOW = datetime(2026, 9, 17, 3, 30, tzinfo=timezone.utc)


def _camera_with_manual_connection() -> tuple[Camera, Recording]:
    camera = Camera(
        id=42,
        name="switch-camera",
        connection_type="manual_rtsp",
        ip="192.0.2.10",
        rtsp_port=8554,
        username="rtsp-user",
        password_encrypted=encrypt_secret("rtsp-secret"),
        rtsp_path="/live/main",
        sub_rtsp_path="/live/sub",
    )
    connection = connection_service.upsert_manual_rtsp_connection(
        camera,
        host="192.0.2.10",
        port=8554,
        username="rtsp-user",
        password_encrypted=camera.password_encrypted,
        main_path="/live/main",
        sub_path="/live/sub",
    )
    connection.id = 77
    history = Recording(id=501, camera_id=42, mp4_path="/recordings/42/history.mp4")
    return camera, history


def test_explicit_switch_preserves_camera_and_connection_identity_across_all_adapters() -> None:
    camera, history = _camera_with_manual_connection()
    original_connection = camera.connection
    assert original_connection is not None
    assert original_connection.revision == 1

    assert hasattr(connection_service, "switch_to_onvif_connection")
    onvif = connection_service.switch_to_onvif_connection(
        camera,
        host="198.51.100.20",
        username="onvif-user",
        password_encrypted=encrypt_secret("onvif-secret"),
        device_service_url="http://198.51.100.20:80/onvif/device_service",
        device_uuid="uuid-20",
        capabilities={"media_xaddr": "http://198.51.100.20/onvif/media"},
        profiles=[{"token": "main"}, {"token": "sub"}],
        recording_profile_token="main",
        preview_profile_token="sub",
        detection_profile_token="sub",
        recording_uri="rtsp://198.51.100.20:8554/onvif/main",
        preview_uri="rtsp://198.51.100.20:8554/onvif/sub",
        detection_uri="rtsp://198.51.100.20:8554/onvif/sub",
        verified_at=NOW,
    )

    assert onvif is original_connection
    assert camera.id == 42
    assert history.camera_id == 42
    assert onvif.id == 77
    assert onvif.adapter == "onvif"
    assert onvif.revision == 2
    assert onvif.rtsp_config is None
    assert onvif.onvif_config is not None
    assert onvif.hik_config is None
    assert onvif.onvif_config.recording_profile_token == "main"
    assert camera.connection_type == "onvif"
    assert camera.ip == "198.51.100.20"
    assert camera.rtsp_port == 8554
    assert camera.rtsp_path == "/onvif/main"
    assert camera.sub_rtsp_path == "/onvif/sub"

    assert hasattr(connection_service, "switch_to_hik_connection")
    hik = connection_service.switch_to_hik_connection(
        camera,
        host="203.0.113.30",
        username="hik-user",
        password_encrypted=encrypt_secret("hik-secret"),
        sdk_port=9000,
        channel=4,
        main_stream_type=0,
        sub_stream_type=1,
        device_serial="HIK-30",
        device_model="DS-2CD-Switch",
        device_name="Switch Gate",
        verified_at=NOW,
    )

    assert hik is original_connection
    assert camera.id == 42
    assert history.camera_id == 42
    assert hik.id == 77
    assert hik.adapter == "hik_sdk"
    assert hik.revision == 3
    assert hik.rtsp_config is None
    assert hik.onvif_config is None
    assert hik.hik_config is not None
    assert hik.hik_config.channel == 4
    assert camera.connection_type == "hik_sdk"
    assert camera.ip == "203.0.113.30"
    assert camera.rtsp_port == 554
    assert camera.rtsp_path == "/hik-sdk/main"
    assert camera.sub_rtsp_path == "/hik-sdk/sub"

    assert hasattr(connection_service, "switch_to_manual_rtsp_connection")
    manual = connection_service.switch_to_manual_rtsp_connection(
        camera,
        host="192.0.2.99",
        port=9554,
        username="new-rtsp-user",
        password_encrypted=encrypt_secret("new-rtsp-secret"),
        main_path="/new/main",
        sub_path="/new/sub",
        verification_status="verified",
        verified_at=NOW,
    )

    assert manual is original_connection
    assert camera.id == 42
    assert history.camera_id == 42
    assert manual.id == 77
    assert manual.adapter == "manual_rtsp"
    assert manual.revision == 4
    assert manual.rtsp_config is not None
    assert manual.onvif_config is None
    assert manual.hik_config is None
    assert manual.rtsp_config.port == 9554
    assert manual.rtsp_config.main_path == "/new/main"
    assert manual.rtsp_config.sub_path == "/new/sub"
    assert camera.connection_type == "manual_rtsp"
    assert camera.ip == "192.0.2.99"
    assert camera.rtsp_port == 9554
    assert camera.rtsp_path == "/new/main"
    assert camera.sub_rtsp_path == "/new/sub"


def test_explicit_switch_requires_an_existing_current_connection() -> None:
    camera = Camera(
        id=43,
        name="legacy-only",
        connection_type="manual_rtsp",
        ip="192.0.2.43",
        rtsp_port=554,
        username="admin",
        password_encrypted=encrypt_secret("legacy-secret"),
        rtsp_path="/main",
    )

    assert hasattr(connection_service, "switch_to_hik_connection")
    try:
        connection_service.switch_to_hik_connection(
            camera,
            host="203.0.113.43",
            username="admin",
            password_encrypted=encrypt_secret("target-secret"),
            sdk_port=8000,
            channel=1,
            main_stream_type=0,
            sub_stream_type=1,
            device_serial=None,
            device_model=None,
            device_name=None,
            verified_at=NOW,
        )
    except ValueError as exc:
        assert str(exc) == "camera has no current connection to switch"
    else:
        raise AssertionError("explicit adapter switch must require a current connection")

    assert camera.connection is None
    assert camera.connection_type == "manual_rtsp"
    assert camera.ip == "192.0.2.43"
