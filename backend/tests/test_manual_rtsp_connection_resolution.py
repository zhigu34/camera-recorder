from types import SimpleNamespace

from app.core.security import encrypt_secret
from app.services.device_adapter import ManualRtspDeviceAdapter


def test_manual_rtsp_resolution_prefers_current_connection_values() -> None:
    camera = SimpleNamespace(
        connection_type="manual_rtsp",
        ip="legacy-camera",
        rtsp_port=554,
        username="legacy-user",
        password_encrypted=encrypt_secret("legacy-secret"),
        rtsp_path="/legacy/main",
        sub_rtsp_path="/legacy/sub",
        connection=SimpleNamespace(
            adapter="manual_rtsp",
            host="current-camera",
            username="current user",
            password_encrypted=encrypt_secret("current secret"),
            rtsp_config=SimpleNamespace(
                port=8554,
                main_path="/current/main",
                sub_path="/current/sub",
            ),
        ),
    )
    adapter = ManualRtspDeviceAdapter()

    preview = adapter.resolve_media_source(camera, "preview")
    recording = adapter.resolve_media_source(camera, "recording")

    assert preview.role == "sub"
    assert preview.uri == (
        "rtsp://current%20user:current%20secret@current-camera:8554/current/sub"
    )
    assert recording.role == "main"
    assert recording.uri == (
        "rtsp://current%20user:current%20secret@current-camera:8554/current/main"
    )


def test_manual_rtsp_resolution_falls_back_to_legacy_camera_without_connection() -> None:
    camera = SimpleNamespace(
        connection_type="manual_rtsp",
        ip="legacy-camera",
        rtsp_port=9554,
        username="legacy user",
        password_encrypted=encrypt_secret("legacy secret"),
        rtsp_path="/legacy/main",
        sub_rtsp_path="/legacy/sub",
    )

    source = ManualRtspDeviceAdapter().resolve_media_source(camera, "preview")

    assert source.role == "sub"
    assert source.uri == "rtsp://legacy%20user:legacy%20secret@legacy-camera:9554/legacy/sub"
