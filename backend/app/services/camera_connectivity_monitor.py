from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.models.camera import Camera
from app.services.event_log import add_event
from app.services.hik_bridge_client import HikBridgeClient, HikBridgeClientError
from app.services.recorder_manager import recorder_manager

_CHECK_INTERVAL_SECONDS = 15.0
_PROBE_TIMEOUT_SECONDS = 2.0
_FAILURE_THRESHOLD = 3
_MAX_CONCURRENCY = 8


@dataclass(frozen=True)
class ConnectivityObservation:
    status: str
    consecutive_failures: int
    source: str


def recorder_runtime_is_healthy(runtime: dict[str, Any] | None) -> bool:
    """Return whether Recorder runtime is a trustworthy positive connectivity signal."""

    if not isinstance(runtime, dict):
        return False
    if str(runtime.get("state") or "STOPPED") != "RECORDING":
        return False
    if runtime.get("pid") is None:
        return False
    if runtime.get("offline_since"):
        return False
    if runtime.get("offline_alert_active"):
        return False
    if runtime.get("continuous_failure_active"):
        return False
    return int(runtime.get("current_offline_seconds") or 0) <= 0


def resolve_connectivity_observation(
    *,
    previous_status: str,
    recorder_state: str,
    recorder_pid: int | None,
    probe_ok: bool | None,
    previous_failures: int,
    probe_source: str = "rtsp",
) -> ConnectivityObservation:
    """Resolve one connectivity observation with recorder priority and failure hysteresis."""

    if recorder_state == "RECORDING" and recorder_pid is not None:
        return ConnectivityObservation(
            status="online",
            consecutive_failures=0,
            source="recorder",
        )

    if probe_ok is True:
        return ConnectivityObservation(
            status="online",
            consecutive_failures=0,
            source=probe_source,
        )

    if probe_ok is False:
        failures = max(0, previous_failures) + 1
        if failures >= _FAILURE_THRESHOLD:
            status = "offline"
        elif previous_status in {"online", "offline"}:
            status = previous_status
        else:
            status = "unknown"
        return ConnectivityObservation(
            status=status,
            consecutive_failures=failures,
            source=probe_source,
        )

    return ConnectivityObservation(
        status=previous_status if previous_status in {"online", "offline"} else "unknown",
        consecutive_failures=max(0, previous_failures),
        source="persisted",
    )


async def _probe_rtsp_method(
    ip: str,
    port: int,
    rtsp_path: str,
    *,
    method: str,
    cseq: int,
    timeout_seconds: float,
) -> tuple[bool, bool]:
    """Return (tcp_connected, valid_rtsp_response) for one control request."""

    host = ip.strip()
    authority = f"[{host}]" if ":" in host and not host.startswith("[") else host
    path = rtsp_path if rtsp_path.startswith("/") else f"/{rtsp_path}"
    writer: asyncio.StreamWriter | None = None
    connected = False
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_seconds,
        )
        connected = True
        headers = [
            f"{method} rtsp://{authority}:{port}{path} RTSP/1.0",
            f"CSeq: {cseq}",
            "User-Agent: CameraRecorder/1.0",
        ]
        if method == "DESCRIBE":
            headers.append("Accept: application/sdp")
        request = "\r\n".join(headers) + "\r\n\r\n"
        writer.write(request.encode("ascii", errors="ignore"))
        await asyncio.wait_for(writer.drain(), timeout=timeout_seconds)
        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout_seconds)
        first_line = response.split(b"\r\n", 1)[0].strip().upper()
        return True, first_line.startswith(b"RTSP/")
    except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        return connected, False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


async def probe_rtsp_service(
    ip: str,
    port: int,
    rtsp_path: str,
    *,
    timeout_seconds: float = _PROBE_TIMEOUT_SECONDS,
) -> bool:
    """Check RTSP control-plane reachability without credentials or media decode."""

    options_connected, options_valid = await _probe_rtsp_method(
        ip,
        port,
        rtsp_path,
        method="OPTIONS",
        cseq=1,
        timeout_seconds=timeout_seconds,
    )
    if options_valid:
        return True
    if not options_connected:
        return False

    _describe_connected, describe_valid = await _probe_rtsp_method(
        ip,
        port,
        rtsp_path,
        method="DESCRIBE",
        cseq=2,
        timeout_seconds=timeout_seconds,
    )
    return describe_valid


async def probe_hik_service(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    bridge_client: HikBridgeClient | None = None,
) -> bool:
    """Check HIK reachability with the adapter's native HCNetSDK login path."""

    client = bridge_client or HikBridgeClient(timeout=_PROBE_TIMEOUT_SECONDS)
    try:
        await client.probe(
            host=host,
            port=port,
            username=username,
            password=password,
        )
        return True
    except HikBridgeClientError:
        return False


@dataclass(frozen=True)
class _CameraTarget:
    camera_id: int
    connection_type: str
    ip: str
    rtsp_port: int
    rtsp_path: str
    username: str
    password_encrypted: str
    hik_sdk_port: int
    previous_status: str
    previous_failures: int


class CameraConnectivityMonitor:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._failures: dict[int, int] = {}
        self._sources: dict[int, str] = {}
        self._last_cycle_at: datetime | None = None
        self._last_cycle_count = 0
        self._error_count = 0
        self._last_error_at: datetime | None = None
        self._last_error: str | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="camera-connectivity-monitor")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except TimeoutError:
                task.cancel()
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                try:
                    await self._record_monitor_error(exc)
                except Exception:
                    pass

            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_CHECK_INTERVAL_SECONDS)
                break
            except TimeoutError:
                pass

    async def _record_monitor_error(self, exc: Exception) -> None:
        observed_at = datetime.now(timezone.utc)
        reason = str(exc)[-1000:] or exc.__class__.__name__
        self._error_count += 1
        self._last_error_at = observed_at
        self._last_error = reason
        async with SessionLocal() as session:
            add_event(
                session,
                level="error",
                category="system",
                code="connectivity_monitor.error",
                message="摄像头连接监控周期失败",
                metadata={"reason": reason, "error_count": self._error_count},
            )
            await session.commit()

    async def check_once(self) -> int:
        runtime_rows = recorder_manager.status()
        runtime_by_camera = {
            int(item["camera_id"]): item
            for item in runtime_rows
            if isinstance(item, dict) and item.get("camera_id") is not None
        }

        async with SessionLocal() as session:
            cameras = list(
                await session.scalars(
                    select(Camera).where(Camera.enabled.is_(True)).order_by(Camera.id)
                )
            )
            targets = [
                _CameraTarget(
                    camera_id=camera.id,
                    connection_type=str(camera.connection_type),
                    ip=camera.ip,
                    rtsp_port=camera.rtsp_port,
                    rtsp_path=camera.rtsp_path,
                    username=camera.username,
                    password_encrypted=camera.password_encrypted,
                    hik_sdk_port=(
                        int(camera.hik_metadata.sdk_port)
                        if camera.hik_metadata is not None
                        else 8000
                    ),
                    previous_status=camera.connectivity_status,
                    previous_failures=camera.connectivity_failures,
                )
                for camera in cameras
            ]

        semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

        async def observe(target: _CameraTarget) -> tuple[int, ConnectivityObservation]:
            runtime = runtime_by_camera.get(target.camera_id, {})
            recorder_healthy = recorder_runtime_is_healthy(runtime)
            recorder_state = str(runtime.get("state") or "STOPPED") if recorder_healthy else "STOPPED"
            recorder_pid = runtime.get("pid") if recorder_healthy else None
            probe_ok: bool | None = None
            probe_source = "hik_sdk" if target.connection_type == "hik_sdk" else "rtsp"
            if not recorder_healthy:
                async with semaphore:
                    if target.connection_type == "hik_sdk":
                        try:
                            password = decrypt_secret(target.password_encrypted)
                            probe_ok = await probe_hik_service(
                                target.ip,
                                target.hik_sdk_port,
                                target.username,
                                password,
                            )
                        except Exception:
                            probe_ok = False
                    else:
                        probe_ok = await probe_rtsp_service(
                            target.ip,
                            target.rtsp_port,
                            target.rtsp_path,
                        )
            previous_failures = self._failures.get(target.camera_id, target.previous_failures)
            result = resolve_connectivity_observation(
                previous_status=target.previous_status,
                recorder_state=recorder_state,
                recorder_pid=int(recorder_pid) if recorder_pid is not None else None,
                probe_ok=probe_ok,
                previous_failures=previous_failures,
                probe_source=probe_source,
            )
            return target.camera_id, result

        results = await asyncio.gather(*(observe(target) for target in targets))
        observed_at = datetime.now(timezone.utc)

        async with SessionLocal() as session:
            for camera_id, result in results:
                camera = await session.get(Camera, camera_id)
                if camera is None or not camera.enabled:
                    continue
                camera.status = result.status
                camera.connectivity_failures = result.consecutive_failures
                camera.last_probe_at = observed_at
                if result.status == "online":
                    camera.last_online_at = observed_at
                self._failures[camera_id] = result.consecutive_failures
                self._sources[camera_id] = result.source
            await session.commit()

        active_ids = {target.camera_id for target in targets}
        self._failures = {
            camera_id: failures
            for camera_id, failures in self._failures.items()
            if camera_id in active_ids
        }
        self._sources = {
            camera_id: source
            for camera_id, source in self._sources.items()
            if camera_id in active_ids
        }
        self._last_cycle_at = observed_at
        self._last_cycle_count = len(results)
        return len(results)

    def reconcile_manual_probe(self, camera_id: int, *, success: bool) -> int:
        if success:
            failures = 0
        else:
            failures = max(_FAILURE_THRESHOLD, self._failures.get(camera_id, 0) + 1)
        self._failures[camera_id] = failures
        self._sources[camera_id] = "manual_probe"
        return failures

    def source_for(self, camera_id: int) -> str | None:
        return self._sources.get(camera_id)

    def failures_for(self, camera_id: int) -> int:
        return self._failures.get(camera_id, 0)

    def snapshot(self) -> dict:
        return {
            "running": bool(self._task and not self._task.done()),
            "interval_seconds": int(_CHECK_INTERVAL_SECONDS),
            "probe_timeout_seconds": _PROBE_TIMEOUT_SECONDS,
            "failure_threshold": _FAILURE_THRESHOLD,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "last_cycle_count": self._last_cycle_count,
            "error_count": self._error_count,
            "last_error_at": self._last_error_at.isoformat() if self._last_error_at else None,
            "last_error": self._last_error,
        }


camera_connectivity_monitor = CameraConnectivityMonitor()
