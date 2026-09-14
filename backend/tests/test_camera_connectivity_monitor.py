import asyncio
from datetime import datetime, timedelta, timezone

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
