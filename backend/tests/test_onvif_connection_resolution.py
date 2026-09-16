from types import SimpleNamespace

import pytest

from app.core.security import encrypt_secret
from app.services.onvif_device_adapter import OnvifDeviceAdapter


def _legacy_metadata() -> SimpleNamespace:
    return SimpleNamespace(
        recording_uri="rtsp://legacy-camera:554/legacy/main",
        preview_uri="rtsp://legacy-camera:554/legacy/sub",
        detection_uri="rtsp://legacy-camera:554/legacy/sub",
        recording_profile_token="legacy-main",
        preview_profile_token="legacy-sub",
        detection_profile_token="legacy-sub",
    )


def test_onvif_resolution_prefers_current_connection_config_and_credentials() -> None:
    camera = SimpleNamespace(
        username="legacy-user",
        password_encrypted=encrypt_secret("legacy-secret"),
        onvif_metadata=_legacy_metadata(),
        connection=SimpleNamespace(
            adapter="onvif",
            username="current user",
            password_encrypted=encrypt_secret("current secret"),
            onvif_config=SimpleNamespace(
                recording_uri="rtsp://current-camera:8554/current/main",
                preview_uri="rtsp://current-camera:8554/current/sub",
                detection_uri="rtsp://current-camera:8554/current/detect",
                recording_profile_token="current-main",
                preview_profile_token="current-sub",
                detection_profile_token="current-detect",
            ),
        ),
    )
    adapter = OnvifDeviceAdapter()

    recording = adapter.resolve_media_source(camera, "recording")
    preview = adapter.resolve_media_source(camera, "preview")
    detection = adapter.resolve_media_source(camera, "detection")

    assert recording.role == "main"
    assert recording.uri == (
        "rtsp://current%20user:current%20secret@current-camera:8554/current/main"
    )
    assert preview.role == "sub"
    assert preview.uri == "rtsp://current%20user:current%20secret@current-camera:8554/current/sub"
    assert detection.role == "sub"
    assert detection.uri == (
        "rtsp://current%20user:current%20secret@current-camera:8554/current/detect"
    )


def test_onvif_current_connection_without_config_does_not_fall_back_to_legacy_metadata() -> None:
    camera = SimpleNamespace(
        username="legacy-user",
        password_encrypted=encrypt_secret("legacy-secret"),
        onvif_metadata=_legacy_metadata(),
        connection=SimpleNamespace(
            adapter="onvif",
            username="current-user",
            password_encrypted=encrypt_secret("current-secret"),
            onvif_config=None,
        ),
    )

    with pytest.raises(ValueError, match="current connection config is missing"):
        OnvifDeviceAdapter().resolve_media_source(camera, "recording")


def test_onvif_resolution_falls_back_to_legacy_metadata_without_current_connection() -> None:
    camera = SimpleNamespace(
        username="legacy user",
        password_encrypted=encrypt_secret("legacy secret"),
        onvif_metadata=_legacy_metadata(),
    )

    source = OnvifDeviceAdapter().resolve_media_source(camera, "preview")

    assert source.role == "sub"
    assert source.uri == "rtsp://legacy%20user:legacy%20secret@legacy-camera:554/legacy/sub"
