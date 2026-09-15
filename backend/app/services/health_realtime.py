import shutil
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.system_settings import SystemSettings
from app.services.camera_connectivity_monitor import (
    camera_connectivity_monitor,
    recorder_runtime_is_healthy,
)
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule import schedule_label
from app.services.recording_schedule_manager import recording_schedule_manager

_PROCESS_STARTED_MONOTONIC = time.monotonic()
_EXPECTED_RECORDING_STATES = {
    "automatic",
    "in_window",
    "manual_override",
    "probe_required",
    "error",
}
_TIMESTAMP_GUIDANCE_THRESHOLD = 5


def _timestamp_guidance(mode: str, warning_count: int) -> dict | None:
    if warning_count < _TIMESTAMP_GUIDANCE_THRESHOLD:
        return None
    if mode == "native":
        return {
            "suggested_mode": "wallclock",
            "message": "时间戳异常较多，建议切换为 wallclock 模式后观察。",
        }
    if mode == "wallclock":
        return {
            "suggested_mode": "reconstruct",
            "message": "wallclock 下仍有时间戳异常，建议先 Probe，再尝试 reconstruct 模式。",
        }
    return {
        "suggested_mode": None,
        "message": "reconstruct 下仍有时间戳异常，建议检查摄像头源流、GOP 与网络稳定性。",
    }


def _storage_snapshot(row: SystemSettings | None) -> dict[str, Any]:
    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(settings.recordings_dir)
    used_percent = (usage.used / usage.total * 100.0) if usage.total else 0.0
    warning_percent = float(row.storage_warning_percent) if row is not None else 80.0
    critical_percent = float(row.storage_critical_percent) if row is not None else 90.0
    if used_percent >= critical_percent:
        state = "critical"
    elif used_percent >= warning_percent:
        state = "warning"
    else:
        state = "healthy"
    return {
        "used_percent": round(used_percent, 2),
        "state": state,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


def _upload_snapshot(row: SystemSettings | None) -> dict[str, Any]:
    if row is None:
        return {"enabled": False, "configured": False, "active": False}
    configured = bool(
        str(row.webdav_url or "").strip()
        and str(row.webdav_username or "").strip()
        and row.webdav_password_encrypted
    )
    enabled = bool(row.upload_enabled)
    return {
        "enabled": enabled,
        "configured": configured,
        "active": enabled and configured,
    }


async def realtime_health_snapshot() -> dict[str, Any]:
    """Build the cheap current-state health contract used by the global status feed.

    This intentionally does not query Recording or UploadTask history. Historical
    availability, completeness and gap diagnosis belong to the reliability read model.
    """

    now = datetime.now(timezone.utc)
    runtime_rows = recorder_manager.status()
    runtime_by_camera = {
        int(item["camera_id"]): item
        for item in runtime_rows
        if isinstance(item, dict) and item.get("camera_id") is not None
    }

    async with SessionLocal() as session:
        cameras = list(await session.scalars(select(Camera).order_by(Camera.id)))
        system_settings = await session.get(SystemSettings, 1)

    camera_rows: list[dict[str, Any]] = []
    enabled_count = 0
    recording_count = 0
    reconnecting_count = 0
    abnormal_count = 0
    online_count = 0
    offline_count = 0
    unknown_count = 0

    for camera in cameras:
        runtime = runtime_by_camera.get(camera.id, {})
        recorder_state = str(runtime.get("state") or camera.recorder_state or "STOPPED")
        if recorder_state == "RECORDING":
            recording_count += 1
        if recorder_state in {"STARTING", "RECONNECTING"}:
            reconnecting_count += 1

        if recorder_runtime_is_healthy(runtime):
            connectivity_status = "online"
            connectivity_source = "recorder"
        else:
            connectivity_status = camera.connectivity_status
            connectivity_source = camera_connectivity_monitor.source_for(camera.id) or "persisted"

        schedule_state = recording_schedule_manager.state_for(camera)
        expected_recording = schedule_state in _EXPECTED_RECORDING_STATES
        timestamp_warning_count = int(runtime.get("timestamp_warning_count") or 0)
        timestamp_mode = str(camera.timestamp_mode or "native")

        if camera.enabled:
            enabled_count += 1
            if connectivity_status == "online":
                online_count += 1
            elif connectivity_status == "offline":
                offline_count += 1
            else:
                unknown_count += 1

        abnormal = bool(
            camera.enabled
            and (
                connectivity_status == "offline"
                or (expected_recording and recorder_state != "RECORDING")
                or runtime.get("offline_alert_active")
            )
        )
        if abnormal:
            abnormal_count += 1

        camera_rows.append(
            {
                "camera_id": camera.id,
                "name": camera.name,
                "ip": camera.ip,
                "enabled": camera.enabled,
                "expected_recording": expected_recording,
                "connectivity_status": connectivity_status,
                "connectivity_source": connectivity_source,
                "connectivity_failures": camera.connectivity_failures,
                "recorder_state": recorder_state,
                "state": recorder_state,
                "schedule_state": schedule_state,
                "schedule_enabled": camera.recording_schedule_enabled,
                "schedule_active": schedule_state in {"in_window", "automatic", "manual_override"},
                "schedule": schedule_label(camera),
                "abnormal": abnormal,
                "pid": runtime.get("pid"),
                "started_at": runtime.get("started_at"),
                "offline_since": runtime.get("offline_since"),
                "current_offline_seconds": int(runtime.get("current_offline_seconds") or 0),
                "restart_count": int(runtime.get("restart_count") or 0),
                "warning_count": int(runtime.get("warning_count") or 0),
                "network_warning_count": int(runtime.get("network_warning_count") or 0),
                "last_error": runtime.get("last_error"),
                "timestamp_mode": timestamp_mode,
                "timestamp_warning_count": timestamp_warning_count,
                "timestamp_guidance": _timestamp_guidance(timestamp_mode, timestamp_warning_count),
            }
        )

    return {
        "generated_at": now.isoformat(),
        "uptime_seconds": max(0, int(time.monotonic() - _PROCESS_STARTED_MONOTONIC)),
        "cameras": {
            "total": len(cameras),
            "enabled": enabled_count,
            "recording": recording_count,
            "reconnecting": reconnecting_count,
            "abnormal": abnormal_count,
            "online": online_count,
            "offline": offline_count,
            "unknown": unknown_count,
        },
        "storage": _storage_snapshot(system_settings),
        "upload": _upload_snapshot(system_settings),
        "connectivity_monitor": camera_connectivity_monitor.snapshot(),
        "camera_health": camera_rows,
    }
