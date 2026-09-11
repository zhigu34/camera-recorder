import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.recording import Recording
from app.models.upload import UploadTask
from app.services.recorder_manager import recorder_manager
from app.services.storage_manager import storage_snapshot

_PROCESS_STARTED_AT = datetime.now(timezone.utc)
_PROCESS_STARTED_MONOTONIC = time.monotonic()


def _recording_stats_defaults() -> dict[str, int]:
    return {
        "segments": 0,
        "unhealthy_segments": 0,
        "failed_segments": 0,
        "warning_count": 0,
        "timestamp_warning_count": 0,
        "network_warning_count": 0,
    }


def _as_int(value: Any) -> int:
    return int(value or 0)


async def health_snapshot() -> dict[str, Any]:
    """Build a low-cost health snapshot from existing runtime and SQLite data."""

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    runtime_rows = recorder_manager.status()
    runtime_by_camera = {
        int(item["camera_id"]): item
        for item in runtime_rows
        if isinstance(item, dict) and item.get("camera_id") is not None
    }

    async with SessionLocal() as session:
        cameras = list(await session.scalars(select(Camera).order_by(Camera.id)))

        recording_rows = (
            await session.execute(
                select(
                    Recording.camera_id,
                    func.count(Recording.id).label("segments"),
                    func.sum(
                        case((Recording.health_status != "healthy", 1), else_=0)
                    ).label("unhealthy_segments"),
                    func.sum(
                        case((Recording.status.not_in(("ready", "deleted")), 1), else_=0)
                    ).label("failed_segments"),
                    func.sum(Recording.warning_count).label("warning_count"),
                    func.sum(Recording.timestamp_warning_count).label("timestamp_warning_count"),
                    func.sum(Recording.network_warning_count).label("network_warning_count"),
                )
                .where(Recording.created_at >= cutoff)
                .group_by(Recording.camera_id)
            )
        ).all()

        upload_rows = (
            await session.execute(
                select(UploadTask.status, func.count(UploadTask.id))
                .group_by(UploadTask.status)
            )
        ).all()

    recording_by_camera: dict[int, dict[str, int]] = {}
    totals = _recording_stats_defaults()
    for row in recording_rows:
        stats = {
            "segments": _as_int(row.segments),
            "unhealthy_segments": _as_int(row.unhealthy_segments),
            "failed_segments": _as_int(row.failed_segments),
            "warning_count": _as_int(row.warning_count),
            "timestamp_warning_count": _as_int(row.timestamp_warning_count),
            "network_warning_count": _as_int(row.network_warning_count),
        }
        recording_by_camera[int(row.camera_id)] = stats
        for key, value in stats.items():
            totals[key] += value

    upload_counts = {
        "pending": 0,
        "uploading": 0,
        "success": 0,
        "failed": 0,
        "retry_wait": 0,
    }
    for status, count in upload_rows:
        upload_counts[str(status)] = _as_int(count)

    camera_rows: list[dict[str, Any]] = []
    recording_count = 0
    reconnecting_count = 0
    abnormal_count = 0
    enabled_count = 0

    for camera in cameras:
        if camera.enabled:
            enabled_count += 1

        runtime = runtime_by_camera.get(camera.id, {})
        runtime_state = str(runtime.get("state") or "STOPPED")
        if runtime_state == "RECORDING":
            recording_count += 1
        if runtime_state in ("RECONNECTING", "STARTING"):
            reconnecting_count += 1

        expected_recording = bool(camera.enabled and camera.auto_record)
        abnormal = bool(
            (expected_recording and runtime_state != "RECORDING")
            or runtime.get("offline_alert_active")
        )
        if abnormal:
            abnormal_count += 1

        camera_rows.append(
            {
                "camera_id": camera.id,
                "name": camera.name,
                "ip": camera.ip,
                "enabled": camera.enabled,
                "auto_record": camera.auto_record,
                "expected_recording": expected_recording,
                "state": runtime_state,
                "abnormal": abnormal,
                "pid": runtime.get("pid"),
                "started_at": runtime.get("started_at"),
                "offline_since": runtime.get("offline_since"),
                "restart_count": _as_int(runtime.get("restart_count")),
                "warning_count": _as_int(runtime.get("warning_count")),
                "timestamp_warning_count": _as_int(runtime.get("timestamp_warning_count")),
                "network_warning_count": _as_int(runtime.get("network_warning_count")),
                "last_error": runtime.get("last_error"),
                "recordings_24h": recording_by_camera.get(
                    camera.id, _recording_stats_defaults()
                ),
            }
        )

    storage = await storage_snapshot()
    uptime_seconds = max(0, int(time.monotonic() - _PROCESS_STARTED_MONOTONIC))

    return {
        "generated_at": now.isoformat(),
        "process_started_at": _PROCESS_STARTED_AT.isoformat(),
        "uptime_seconds": uptime_seconds,
        "cameras": {
            "total": len(cameras),
            "enabled": enabled_count,
            "recording": recording_count,
            "reconnecting": reconnecting_count,
            "abnormal": abnormal_count,
        },
        "recordings_24h": totals,
        "uploads": upload_counts,
        "storage": storage,
        "camera_health": camera_rows,
    }
