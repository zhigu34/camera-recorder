import asyncio

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.main import app
from app.models import Camera


async def _connection_snapshot(camera_id: int) -> dict:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        assert camera is not None
        connection = camera.connection
        assert connection is not None
        return {
            "id": connection.id,
            "adapter": connection.adapter,
            "host": connection.host,
            "username": connection.username,
            "password_encrypted": connection.password_encrypted,
            "revision": connection.revision,
            "verification_status": connection.verification_status,
            "verified_at": connection.verified_at,
            "last_error": connection.last_error,
        }


def _manual_camera_payload(name: str) -> dict:
    return {
        "name": name,
        "ip": "192.0.2.71",
        "rtsp_port": 8554,
        "username": "viewer",
        "password": "stored-secret",
        "rtsp_path": "/main",
        "sub_rtsp_path": "/sub",
    }


def test_unified_draft_probe_returns_standard_envelope_without_persistence(monkeypatch) -> None:
    from app.api import camera_connections as probe_api

    calls = []

    async def fake_probe(draft, *, password: str, rtsp_timeout_us: int):
        calls.append((draft.adapter, password, rtsp_timeout_us))
        return {
            "adapter": draft.adapter,
            "ok": True,
            "device": {},
            "media": {"video_codec": "h264", "width": 1920, "height": 1080},
            "connection_cache": {},
        }

    monkeypatch.setattr(probe_api, "probe_connection_draft", fake_probe)

    with TestClient(app) as client:
        response = client.post(
            "/api/camera-connections/probe",
            json={
                "connection": {
                    "adapter": "manual_rtsp",
                    "host": "192.0.2.70",
                    "username": "admin",
                    "password": "draft-secret",
                    "port": 554,
                    "main_path": "/live/main",
                    "sub_path": "/live/sub",
                }
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "adapter": "manual_rtsp",
        "ok": True,
        "device": {},
        "media": {"video_codec": "h264", "width": 1920, "height": 1080},
        "connection_cache": {},
    }
    assert len(calls) == 1
    assert calls[0][0:2] == ("manual_rtsp", "draft-secret")
    assert calls[0][2] > 0


def test_same_adapter_probe_reuses_stored_password_without_mutating_connection(monkeypatch) -> None:
    from app.api import camera_connections as probe_api

    seen_passwords: list[str] = []

    async def fake_probe(draft, *, password: str, rtsp_timeout_us: int):
        seen_passwords.append(password)
        assert draft.adapter == "manual_rtsp"
        assert rtsp_timeout_us > 0
        return {
            "adapter": "manual_rtsp",
            "ok": True,
            "device": {},
            "media": {},
            "connection_cache": {},
        }

    monkeypatch.setattr(probe_api, "probe_connection_draft", fake_probe)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_manual_camera_payload("probe-password-reuse"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_connection_snapshot(camera_id))
        assert decrypt_secret(before["password_encrypted"]) == "stored-secret"

        response = client.post(
            "/api/camera-connections/probe",
            json={
                "camera_id": camera_id,
                "connection": {
                    "adapter": "manual_rtsp",
                    "host": "192.0.2.71",
                    "username": "viewer",
                    "port": 8554,
                    "main_path": "/main",
                    "sub_path": "/sub",
                },
            },
        )
        assert response.status_code == 200, response.text
        after = asyncio.run(_connection_snapshot(camera_id))

        missing_cross_adapter_password = client.post(
            "/api/camera-connections/probe",
            json={
                "camera_id": camera_id,
                "connection": {
                    "adapter": "onvif",
                    "host": "192.0.2.72",
                    "username": "admin",
                    "port": 80,
                },
            },
        )
        assert missing_cross_adapter_password.status_code == 422

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204

    assert seen_passwords == ["stored-secret"]
    assert after == before


def test_new_draft_without_password_is_rejected_before_probe(monkeypatch) -> None:
    from app.api import camera_connections as probe_api

    called = False

    async def fake_probe(draft, *, password: str, rtsp_timeout_us: int):
        nonlocal called
        called = True
        return {
            "adapter": draft.adapter,
            "ok": True,
            "device": {},
            "media": {},
            "connection_cache": {},
        }

    monkeypatch.setattr(probe_api, "probe_connection_draft", fake_probe)

    with TestClient(app) as client:
        response = client.post(
            "/api/camera-connections/probe",
            json={
                "connection": {
                    "adapter": "onvif",
                    "host": "192.0.2.73",
                    "username": "admin",
                    "port": 80,
                }
            },
        )

    assert response.status_code == 422
    assert called is False


def test_disabled_hik_draft_probe_returns_503_without_bridge_call(monkeypatch) -> None:
    from app.services import camera_adapter_probe as adapter_probe
    from app.services import camera_adapter_registry as registry

    monkeypatch.setattr(registry.settings, "hik_enabled", False)
    bridge_constructions = 0

    def unexpected_bridge(*args, **kwargs):
        nonlocal bridge_constructions
        bridge_constructions += 1
        raise AssertionError("disabled HIK draft probe must not construct a bridge client")

    monkeypatch.setattr(adapter_probe, "HikBridgeClient", unexpected_bridge)

    with TestClient(app) as client:
        response = client.post(
            "/api/camera-connections/probe",
            json={
                "connection": {
                    "adapter": "hik_sdk",
                    "host": "192.0.2.74",
                    "username": "admin",
                    "password": "draft-secret",
                    "sdk_port": 8000,
                    "channel": 1,
                    "main_stream_type": 0,
                    "sub_stream_type": 1,
                }
            },
        )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == registry.HIK_DISABLED_REASON
    assert bridge_constructions == 0
    assert "draft-secret" not in response.text
