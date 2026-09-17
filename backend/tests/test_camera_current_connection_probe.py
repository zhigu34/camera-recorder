from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import cameras as cameras_api
from app.core.database import SessionLocal
from app.main import app
from app.models import Camera
from app.services.camera_adapter_probe import (
    CameraAdapterProbeError,
    CameraConnectionProbeResult,
)
from app.services.camera_probe import CameraProbeError


def _create_payload(adapter: str) -> dict:
    connection: dict
    if adapter == "manual_rtsp":
        connection = {
            "adapter": "manual_rtsp",
            "host": "192.0.2.81",
            "username": "operator",
            "password": "secret",
            "port": 8554,
            "main_path": "/main",
            "sub_path": "/sub",
        }
    elif adapter == "onvif":
        connection = {
            "adapter": "onvif",
            "host": "192.0.2.82",
            "username": "operator",
            "password": "secret",
            "port": 8080,
        }
    else:
        connection = {
            "adapter": "hik_sdk",
            "host": "192.0.2.83",
            "username": "operator",
            "password": "secret",
            "sdk_port": 9000,
            "channel": 2,
            "main_stream_type": 0,
            "sub_stream_type": 1,
        }
    return {
        "name": f"current-probe-{adapter}-{uuid.uuid4().hex[:10]}",
        "enabled": False,
        "auto_record": False,
        "timestamp_mode": "native",
        "connection": connection,
    }


def _probe_result(adapter: str) -> CameraConnectionProbeResult:
    media = {
        "ok": True,
        "video_codec": "h264",
        "video_profile": "High",
        "width": 1920,
        "height": 1080,
        "fps_num": 20,
        "fps_den": 1,
        "fps": 20.0,
        "pixel_format": "yuv420p",
        "has_b_frames": 0,
        "video_time_base": "1/90000",
        "audio_codec": "aac",
        "audio_profile": "LC",
        "sample_rate": 48000,
        "channels": 1,
        "audio_frame_samples": 1024,
    }
    if adapter == "manual_rtsp":
        return CameraConnectionProbeResult(
            adapter="manual_rtsp",
            device={},
            media=media,
            connection_cache={
                "port": 8554,
                "main_path": "/main",
                "sub_path": "/sub",
            },
        )
    if adapter == "onvif":
        return CameraConnectionProbeResult(
            adapter="onvif",
            device={
                "manufacturer": "Acme",
                "model": "ProbeCam",
                "firmware_version": "1.0",
                "serial_number": "ONVIF-1",
                "hardware_id": "HW-1",
            },
            media=media,
            connection_cache={
                "device_service_url": "http://192.0.2.82:8080/onvif/device_service",
                "device_uuid": "uuid-onvif-1",
                "capabilities": {"media_xaddr": "http://192.0.2.82/onvif/media"},
                "profiles": [
                    {
                        "token": "main",
                        "name": "Main",
                        "encoding": "H264",
                        "width": 1920,
                        "height": 1080,
                        "fps": 20.0,
                        "uri": "rtsp://192.0.2.82:8554/main",
                    }
                ],
                "recording_profile_token": "main",
                "preview_profile_token": "main",
                "detection_profile_token": "main",
                "recording_uri": "rtsp://192.0.2.82:8554/main",
                "preview_uri": "rtsp://192.0.2.82:8554/main",
                "detection_uri": "rtsp://192.0.2.82:8554/main",
            },
        )
    return CameraConnectionProbeResult(
        adapter="hik_sdk",
        device={
            "serial_number": "HIK-1",
            "device_type": 42,
            "device_model": "DS-2CD-Probe",
            "device_name": "Probe Gate",
        },
        media=media,
        connection_cache={
            "sdk_port": 9000,
            "channel": 2,
            "main_stream_type": 0,
            "sub_stream_type": 1,
            "device_serial": "HIK-1",
            "device_model": "DS-2CD-Probe",
            "device_name": "Probe Gate",
        },
    )


async def _snapshot(camera_id: int) -> dict:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        assert camera is not None
        connection = camera.connection
        assert connection is not None
        target: dict[str, object] = {
            "adapter": connection.adapter,
            "host": connection.host,
            "username": connection.username,
        }
        cache: dict[str, object] = {}
        if connection.adapter == "manual_rtsp":
            config = connection.rtsp_config
            assert config is not None
            target.update(
                {
                    "port": config.port,
                    "main_path": config.main_path,
                    "sub_path": config.sub_path,
                }
            )
        elif connection.adapter == "onvif":
            config = connection.onvif_config
            assert config is not None
            target["device_service_url"] = config.device_service_url
            cache = {
                "device_uuid": config.device_uuid,
                "recording_profile_token": config.recording_profile_token,
                "recording_uri": config.recording_uri,
            }
        else:
            config = connection.hik_config
            assert config is not None
            target.update(
                {
                    "sdk_port": config.sdk_port,
                    "channel": config.channel,
                    "main_stream_type": config.main_stream_type,
                    "sub_stream_type": config.sub_stream_type,
                }
            )
            cache = {
                "device_serial": config.device_serial,
                "device_model": config.device_model,
                "device_name": config.device_name,
            }
        return {
            "revision": connection.revision,
            "password_encrypted": connection.password_encrypted,
            "verification_status": connection.verification_status,
            "verified_at": connection.verified_at,
            "last_error": connection.last_error,
            "target": target,
            "cache": cache,
            "video_codec": camera.video_codec,
            "width": camera.width,
            "status": camera.status,
        }


@pytest.mark.parametrize("adapter", ["manual_rtsp", "onvif", "hik_sdk"])
def test_saved_current_connection_probe_persists_verification_without_revision_bump(
    adapter: str,
    monkeypatch,
) -> None:
    result = _probe_result(adapter)

    async def fake_saved_probe(_camera, *, rtsp_timeout_us: int):
        assert rtsp_timeout_us > 0
        return result

    async def legacy_probe(_camera, *, rtsp_timeout_us: int):
        assert rtsp_timeout_us > 0
        return result.media

    monkeypatch.setattr(cameras_api, "probe_saved_connection", fake_saved_probe, raising=False)
    monkeypatch.setattr(cameras_api, "probe_camera_media", legacy_probe)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_create_payload(adapter))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))
        assert before["verification_status"] == "unverified"

        response = client.post(f"/api/cameras/{camera_id}/probe")
        assert response.status_code == 200, response.text
        after = asyncio.run(_snapshot(camera_id))

    assert after["revision"] == before["revision"]
    assert after["password_encrypted"] == before["password_encrypted"]
    assert after["target"] == before["target"]
    assert after["verification_status"] == "verified"
    assert after["verified_at"] is not None
    assert after["last_error"] is None
    assert after["video_codec"] == "h264"
    assert after["width"] == 1920
    assert after["status"] == "online"
    if adapter == "onvif":
        assert after["cache"] == {
            "device_uuid": "uuid-onvif-1",
            "recording_profile_token": "main",
            "recording_uri": "rtsp://192.0.2.82:8554/main",
        }
    elif adapter == "hik_sdk":
        assert after["cache"] == {
            "device_serial": "HIK-1",
            "device_model": "DS-2CD-Probe",
            "device_name": "Probe Gate",
        }


@pytest.mark.parametrize("adapter", ["manual_rtsp", "onvif", "hik_sdk"])
def test_saved_current_connection_probe_failure_preserves_target_and_revision(
    adapter: str,
    monkeypatch,
) -> None:
    async def fake_saved_probe(_camera, *, rtsp_timeout_us: int):
        assert rtsp_timeout_us > 0
        raise CameraAdapterProbeError("saved connection probe failed")

    async def legacy_probe(_camera, *, rtsp_timeout_us: int):
        assert rtsp_timeout_us > 0
        raise CameraProbeError("legacy probe failed")

    monkeypatch.setattr(cameras_api, "probe_saved_connection", fake_saved_probe, raising=False)
    monkeypatch.setattr(cameras_api, "probe_camera_media", legacy_probe)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_create_payload(adapter))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        response = client.post(f"/api/cameras/{camera_id}/probe")
        assert response.status_code == 502, response.text
        after = asyncio.run(_snapshot(camera_id))

    assert after["revision"] == before["revision"]
    assert after["password_encrypted"] == before["password_encrypted"]
    assert after["target"] == before["target"]
    assert after["verification_status"] == "failed"
    assert after["last_error"] == "saved connection probe failed"
    assert after["status"] == "offline"
