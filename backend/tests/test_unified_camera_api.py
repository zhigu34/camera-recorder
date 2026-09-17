from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.main import app
from app.models import Camera
from app.services.camera_runtime_coordinator import RuntimeStopSnapshot


class _CoordinatorSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.snapshot = RuntimeStopSnapshot(was_recording=False, recording_owner=None)

    async def stop_all(self, camera_id: int, *, forget_schedule: bool = False):
        self.calls.append(("stop", camera_id, forget_schedule))
        return self.snapshot

    async def restore(
        self,
        camera_id: int,
        snapshot: RuntimeStopSnapshot,
        *,
        schedule_changed: bool = False,
    ) -> str:
        assert snapshot is self.snapshot
        self.calls.append(("restore", camera_id, schedule_changed))
        return "running"

    async def reload(self, camera_id: int, *, schedule_changed: bool = False) -> str:
        self.calls.append(("reload", camera_id, schedule_changed))
        return "running"


class _FailingRestoreCoordinator(_CoordinatorSpy):
    async def restore(
        self,
        camera_id: int,
        snapshot: RuntimeStopSnapshot,
        *,
        schedule_changed: bool = False,
    ) -> str:
        await super().restore(camera_id, snapshot, schedule_changed=schedule_changed)
        raise RuntimeError("runtime restore failed")


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _connection(adapter: str, *, host: str = "192.0.2.80", password: str | None = "secret") -> dict:
    base = {"adapter": adapter, "host": host, "username": "operator"}
    if password is not None:
        base["password"] = password
    if adapter == "manual_rtsp":
        return {**base, "port": 8554, "main_path": "/main", "sub_path": "/sub"}
    if adapter == "onvif":
        return {**base, "port": 8080}
    if adapter == "hik_sdk":
        return {
            **base,
            "sdk_port": 9000,
            "channel": 2,
            "main_stream_type": 0,
            "sub_stream_type": 1,
        }
    raise AssertionError(adapter)


def _create_payload(adapter: str, *, name: str | None = None, host: str = "192.0.2.80") -> dict:
    return {
        "name": name or _name(f"unified-{adapter}"),
        "enabled": False,
        "auto_record": False,
        "timestamp_mode": "native",
        "connection": _connection(adapter, host=host),
    }


async def _snapshot(camera_id: int) -> dict:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        assert camera is not None
        connection = camera.connection
        assert connection is not None
        return {
            "camera_id": camera.id,
            "name": camera.name,
            "connection_id": connection.id,
            "adapter": connection.adapter,
            "host": connection.host,
            "username": connection.username,
            "password_encrypted": connection.password_encrypted,
            "revision": connection.revision,
            "verification_status": connection.verification_status,
            "rtsp": connection.rtsp_config is not None,
            "onvif": connection.onvif_config is not None,
            "hik": connection.hik_config is not None,
            "legacy_type": camera.connection_type,
        }


@pytest.mark.parametrize("adapter", ["manual_rtsp", "onvif", "hik_sdk"])
def test_unified_create_saves_each_adapter_unverified_without_probe(adapter: str) -> None:
    with TestClient(app) as client:
        response = client.post("/api/cameras", json=_create_payload(adapter))
        assert response.status_code == 201, response.text
        body = response.json()
        camera_id = int(body["id"])

        assert body["connection"]["adapter"] == adapter
        assert body["connection"]["verification_status"] == "unverified"
        assert body["connection"]["password_set"] is True
        assert "password" not in body["connection"]
        assert "password_encrypted" not in body["connection"]

        snapshot = asyncio.run(_snapshot(camera_id))
        assert snapshot["adapter"] == adapter
        assert snapshot["revision"] == 1
        assert snapshot["verification_status"] == "unverified"
        assert sum((snapshot["rtsp"], snapshot["onvif"], snapshot["hik"])) == 1

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


@pytest.mark.parametrize("adapter", ["manual_rtsp", "onvif", "hik_sdk"])
def test_same_adapter_real_edit_reuses_password_and_increments_revision_once(
    adapter: str,
    monkeypatch,
) -> None:
    from app.services import camera_mutation

    spy = _CoordinatorSpy()
    monkeypatch.setattr(camera_mutation, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_create_payload(adapter))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        connection = _connection(adapter, host="192.0.2.81", password=None)
        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={"connection": connection},
        )
        assert updated.status_code == 200, updated.text
        after = asyncio.run(_snapshot(camera_id))

        assert after["camera_id"] == before["camera_id"]
        assert after["connection_id"] == before["connection_id"]
        assert after["revision"] == before["revision"] + 1
        assert after["verification_status"] == "unverified"
        assert after["password_encrypted"] == before["password_encrypted"]
        assert decrypt_secret(after["password_encrypted"]) == "secret"
        assert spy.calls == [("reload", camera_id, False)]

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


def test_metadata_only_edit_on_non_manual_camera_does_not_reload_or_bump_revision(monkeypatch) -> None:
    from app.services import camera_mutation

    spy = _CoordinatorSpy()
    monkeypatch.setattr(camera_mutation, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_create_payload("onvif"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        new_name = _name("unified-renamed")
        updated = client.put(f"/api/cameras/{camera_id}", json={"name": new_name})
        assert updated.status_code == 200, updated.text
        after = asyncio.run(_snapshot(camera_id))

        assert after["connection_id"] == before["connection_id"]
        assert after["revision"] == before["revision"]
        assert after["name"] == new_name
        assert spy.calls == []

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


@pytest.mark.parametrize("target", ["manual_rtsp", "onvif", "hik_sdk"])
def test_cross_adapter_switch_keeps_ids_and_replaces_only_target_config(target: str, monkeypatch) -> None:
    from app.services import camera_mutation

    source = "onvif" if target == "manual_rtsp" else "manual_rtsp"
    spy = _CoordinatorSpy()
    monkeypatch.setattr(camera_mutation, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_create_payload(source))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={"connection": _connection(target, host="198.51.100.90")},
        )
        assert updated.status_code == 200, updated.text
        after = asyncio.run(_snapshot(camera_id))

        assert after["camera_id"] == before["camera_id"]
        assert after["connection_id"] == before["connection_id"]
        assert after["revision"] == before["revision"] + 1
        assert after["adapter"] == target
        assert after["legacy_type"] == target
        assert after["verification_status"] == "unverified"
        assert sum((after["rtsp"], after["onvif"], after["hik"])) == 1
        assert spy.calls == [("stop", camera_id, False), ("restore", camera_id, False)]

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


def test_cross_adapter_switch_requires_target_password_before_runtime_stop(monkeypatch) -> None:
    from app.services import camera_mutation

    spy = _CoordinatorSpy()
    monkeypatch.setattr(camera_mutation, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_create_payload("manual_rtsp"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={"connection": _connection("onvif", password=None)},
        )
        after = asyncio.run(_snapshot(camera_id))

        assert updated.status_code == 422, updated.text
        assert after == before
        assert spy.calls == []

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


def test_invalid_schedule_fails_before_cross_adapter_runtime_stop(monkeypatch) -> None:
    from app.services import camera_mutation

    spy = _CoordinatorSpy()
    monkeypatch.setattr(camera_mutation, "camera_runtime_coordinator", spy)

    with TestClient(app) as client:
        created = client.post("/api/cameras", json=_create_payload("manual_rtsp"))
        assert created.status_code == 201, created.text
        camera_id = int(created.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "recording_schedule_enabled": True,
                "recording_schedule": [],
                "connection": _connection("hik_sdk"),
            },
        )
        after = asyncio.run(_snapshot(camera_id))

        assert updated.status_code == 422, updated.text
        assert after == before
        assert spy.calls == []

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


def test_cross_adapter_commit_failure_rolls_back_and_restores_old_connection(monkeypatch) -> None:
    from app.services import camera_mutation

    spy = _CoordinatorSpy()
    monkeypatch.setattr(camera_mutation, "camera_runtime_coordinator", spy)

    blocker_name = _name("unified-blocker")
    with TestClient(app) as client:
        blocker = client.post(
            "/api/cameras",
            json=_create_payload("manual_rtsp", name=blocker_name, host="192.0.2.91"),
        )
        assert blocker.status_code == 201, blocker.text
        source = client.post("/api/cameras", json=_create_payload("manual_rtsp", host="192.0.2.92"))
        assert source.status_code == 201, source.text
        camera_id = int(source.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "name": blocker_name,
                "connection": _connection("onvif", host="198.51.100.92"),
            },
        )
        after = asyncio.run(_snapshot(camera_id))

        assert updated.status_code == 409, updated.text
        assert after == before
        assert spy.calls == [("stop", camera_id, False), ("restore", camera_id, False)]


def test_post_commit_restore_failure_keeps_new_connection_persisted(monkeypatch) -> None:
    from app.services import camera_mutation

    spy = _FailingRestoreCoordinator()
    monkeypatch.setattr(camera_mutation, "camera_runtime_coordinator", spy)

    with TestClient(app, raise_server_exceptions=False) as client:
        source = client.post("/api/cameras", json=_create_payload("manual_rtsp"))
        assert source.status_code == 201, source.text
        camera_id = int(source.json()["id"])
        before = asyncio.run(_snapshot(camera_id))

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={"connection": _connection("hik_sdk", host="203.0.113.93")},
        )
        after = asyncio.run(_snapshot(camera_id))

    assert updated.status_code == 500, updated.text
    assert after["camera_id"] == before["camera_id"]
    assert after["connection_id"] == before["connection_id"]
    assert after["revision"] == before["revision"] + 1
    assert after["adapter"] == "hik_sdk"
    assert after["hik"] is True
    assert after["rtsp"] is False
    assert spy.calls == [("stop", camera_id, False), ("restore", camera_id, False)]
