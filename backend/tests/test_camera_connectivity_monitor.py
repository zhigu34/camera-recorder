import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.camera import Camera


def test_recording_runtime_is_immediate_online_signal() -> None:
    from app.services.camera_connectivity_monitor import resolve_connectivity_observation

    result = resolve_connectivity_observation(
        previous_status="offline",
        recorder_state="RECORDING",
        recorder_pid=1234,
        probe_ok=None,
        previous_failures=2,
    )

    assert result.status == "online"
    assert result.consecutive_failures == 0
    assert result.source == "recorder"


def test_rtsp_failures_need_three_consecutive_misses() -> None:
    from app.services.camera_connectivity_monitor import resolve_connectivity_observation

    first = resolve_connectivity_observation(
        previous_status="online",
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=False,
        previous_failures=0,
    )
    second = resolve_connectivity_observation(
        previous_status=first.status,
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=False,
        previous_failures=first.consecutive_failures,
    )
    third = resolve_connectivity_observation(
        previous_status=second.status,
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=False,
        previous_failures=second.consecutive_failures,
    )

    assert first.status == "online"
    assert second.status == "online"
    assert third.status == "offline"
    assert third.consecutive_failures == 3
    assert third.source == "rtsp"


def test_single_rtsp_success_recovers_offline_camera() -> None:
    from app.services.camera_connectivity_monitor import resolve_connectivity_observation

    result = resolve_connectivity_observation(
        previous_status="offline",
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=True,
        previous_failures=3,
    )

    assert result.status == "online"
    assert result.consecutive_failures == 0
    assert result.source == "rtsp"


@pytest.mark.asyncio
async def test_lightweight_probe_accepts_any_rtsp_response() -> None:
    from app.services.camera_connectivity_monitor import probe_rtsp_service

    request_seen = asyncio.Event()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        assert request.startswith(b"OPTIONS rtsp://")
        request_seen.set()
        writer.write(b"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await probe_rtsp_service("127.0.0.1", port, "/stream", timeout_seconds=1.0)
        assert request_seen.is_set()
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_rtsp_probe_retries_with_describe_when_options_connection_closes() -> None:
    from app.services.camera_connectivity_monitor import probe_rtsp_service

    requests: list[bytes] = []

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        requests.append(request)
        if request.startswith(b"OPTIONS "):
            writer.close()
            await writer.wait_closed()
            return
        writer.write(b"RTSP/1.0 401 Unauthorized\r\nCSeq: 2\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await probe_rtsp_service("127.0.0.1", port, "/stream", timeout_seconds=1.0)
        assert len(requests) == 2
        assert requests[0].startswith(b"OPTIONS ")
        assert requests[1].startswith(b"DESCRIBE ")
    finally:
        server.close()
        await server.wait_closed()


def test_stale_persisted_online_state_becomes_unknown() -> None:
    stale = datetime.now(timezone.utc) - timedelta(seconds=90)
    camera = Camera(
        name="stale-connectivity",
        ip="192.0.2.10",
        password_encrypted="unused",
        status="online",
        last_probe_at=stale,
        last_online_at=stale,
    )

    assert camera.connectivity_status == "unknown"


def test_connectivity_failure_streak_is_persisted_on_camera_model() -> None:
    camera = Camera(
        name="persisted-failures",
        ip="192.0.2.11",
        password_encrypted="unused",
    )
    assert camera.connectivity_failures == 0
    camera.connectivity_failures = 2
    assert camera.connectivity_failures == 2


def test_recorder_signal_is_rejected_when_runtime_reports_outage() -> None:
    from app.services.camera_connectivity_monitor import recorder_runtime_is_healthy

    assert recorder_runtime_is_healthy({"state": "RECORDING", "pid": 123, "offline_since": None}) is True
    assert recorder_runtime_is_healthy({"state": "RECORDING", "pid": 123, "offline_since": "2026-09-15T00:00:00+00:00"}) is False
    assert recorder_runtime_is_healthy({"state": "RECORDING", "pid": 123, "continuous_failure_active": True}) is False


@pytest.mark.asyncio
async def test_monitor_runs_first_cycle_immediately(monkeypatch) -> None:
    from app.services.camera_connectivity_monitor import CameraConnectivityMonitor

    monitor = CameraConnectivityMonitor()
    calls = 0

    async def check_once() -> int:
        nonlocal calls
        calls += 1
        monitor._stop.set()
        return 0

    monkeypatch.setattr(monitor, "check_once", check_once)
    await asyncio.wait_for(monitor._run(), timeout=0.25)
    assert calls == 1


@pytest.mark.asyncio
async def test_monitor_records_unexpected_cycle_error(monkeypatch) -> None:
    from app.services.camera_connectivity_monitor import CameraConnectivityMonitor

    monitor = CameraConnectivityMonitor()
    recorded: list[str] = []

    async def check_once() -> int:
        monitor._stop.set()
        raise RuntimeError("boom")

    async def record_error(exc: Exception) -> None:
        recorded.append(str(exc))

    monkeypatch.setattr(monitor, "check_once", check_once)
    monkeypatch.setattr(monitor, "_record_monitor_error", record_error)
    await asyncio.wait_for(monitor._run(), timeout=0.25)
    assert recorded == ["boom"]


def test_manual_probe_reconciles_monitor_failure_streak() -> None:
    from app.services.camera_connectivity_monitor import CameraConnectivityMonitor

    monitor = CameraConnectivityMonitor()
    monitor._failures[9] = 3
    monitor.reconcile_manual_probe(9, success=True)
    assert monitor.failures_for(9) == 0

    monitor.reconcile_manual_probe(9, success=False)
    assert monitor.failures_for(9) >= 1


@pytest.mark.asyncio
async def test_monitor_skips_unavailable_hik_without_mutating_connectivity(monkeypatch) -> None:
    from app.core.database import SessionLocal
    from app.services import camera_connectivity_monitor as monitor_module

    observed_at = datetime.now(timezone.utc)
    camera = Camera(
        name=f"hik-unavailable-{uuid.uuid4().hex[:10]}",
        connection_type="hik_sdk",
        ip="192.0.2.90",
        username="admin",
        password_encrypted="must-not-be-decrypted",
        rtsp_path="/hik-sdk/main",
        enabled=True,
        status="online",
        connectivity_failures=2,
        last_probe_at=observed_at,
        last_online_at=observed_at,
    )
    async with SessionLocal() as db:
        db.add(camera)
        await db.commit()
        await db.refresh(camera)
        camera_id = camera.id

    capability_calls = 0
    decrypt_calls = 0
    hik_probe_calls = 0

    async def unavailable(adapter: str):
        nonlocal capability_calls
        capability_calls += 1
        assert adapter == "hik_sdk"
        return SimpleNamespace(
            id="hik_sdk",
            available=False,
            unavailable_reason="HIK SDK adapter is disabled by deployment configuration",
        )

    def unexpected_decrypt(_value: str) -> str:
        nonlocal decrypt_calls
        decrypt_calls += 1
        raise AssertionError("unavailable HIK must not decrypt credentials for probing")

    async def unexpected_hik_probe(*args, **kwargs) -> bool:
        nonlocal hik_probe_calls
        hik_probe_calls += 1
        raise AssertionError("unavailable HIK must not probe the bridge")

    monkeypatch.setattr(monitor_module.recorder_manager, "status", lambda: [])
    monkeypatch.setattr(
        monitor_module,
        "get_camera_adapter_capability",
        unavailable,
        raising=False,
    )
    monkeypatch.setattr(monitor_module, "decrypt_secret", unexpected_decrypt)
    monkeypatch.setattr(monitor_module, "probe_hik_service", unexpected_hik_probe)

    monitor = monitor_module.CameraConnectivityMonitor()
    try:
        await monitor.check_once()
        async with SessionLocal() as db:
            persisted = await db.get(Camera, camera_id)
            assert persisted is not None
            assert persisted.status == "online"
            assert persisted.connectivity_failures == 2
            assert persisted.last_probe_at == observed_at
            assert persisted.last_online_at == observed_at
    finally:
        async with SessionLocal() as db:
            persisted = await db.get(Camera, camera_id)
            if persisted is not None:
                await db.delete(persisted)
                await db.commit()

    assert capability_calls == 1
    assert decrypt_calls == 0
    assert hik_probe_calls == 0
