from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.camera import Camera
from app.models.event import Event
from app.schemas.event import EventRead
from app.schemas.notification_settings import EmailRecipient
from app.schemas.operations import (
    OperationsCameraBackup,
    OperationsConfigurationBackup,
    OperationsNotificationBackup,
    OperationsRestoreResult,
    OperationsSystemBackup,
)
from app.services.camera_connectivity_monitor import camera_connectivity_monitor
from app.services.event_log import add_event
from app.services.notification_settings import (
    get_or_create_notification_settings,
    parse_email_recipients,
    serialize_email_recipients,
)
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule_manager import recording_schedule_manager
from app.services.system_settings import get_or_create_system_settings

router = APIRouter(tags=["operations"])

_SYSTEM_FIELDS = (
    "app_name",
    "segment_duration_seconds",
    "remux_concurrency",
    "rtsp_timeout_us",
    "auto_start_enabled",
    "align_segments_to_clock",
    "storage_warning_percent",
    "storage_critical_percent",
    "upload_enabled",
    "upload_concurrency",
    "upload_retry_max",
    "webdav_url",
    "webdav_root",
    "webdav_username",
    "local_retention_hours",
)
_NOTIFICATION_FIELDS = (
    "email_enabled",
    "offline_alert_seconds",
    "recovery_stable_seconds",
    "notify_recovery",
    "smtp_sender_name",
    "smtp_host",
    "smtp_port",
    "smtp_auth_enabled",
    "smtp_username",
    "smtp_from",
    "smtp_to",
    "smtp_use_ssl",
    "smtp_starttls",
    "smtp_timeout_seconds",
    "email_attach_images",
    "email_capture_interval_seconds",
)
_CAMERA_FIELDS = (
    "name",
    "manufacturer",
    "model",
    "form_factor",
    "ip",
    "rtsp_port",
    "username",
    "rtsp_path",
    "sub_rtsp_path",
    "enabled",
    "auto_record",
    "recording_schedule_enabled",
    "recording_schedule",
    "timestamp_mode",
)


def _safe_log_path(name: str) -> Path:
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid log file name")
    raw = Path(name)
    if raw.is_absolute() or raw.name != name:
        raise HTTPException(status_code=400, detail="invalid log file name")

    root = settings.logs_dir.resolve()
    candidate = root / name
    if candidate.is_symlink():
        raise HTTPException(status_code=400, detail="symbolic log links are not allowed")
    resolved = candidate.resolve()
    if resolved.parent != root:
        raise HTTPException(status_code=400, detail="invalid log file path")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="log file not found")
    return resolved


@router.get("/api/operations/logs")
async def list_operation_logs() -> list[dict]:
    root = settings.logs_dir
    root.mkdir(parents=True, exist_ok=True)
    result: list[dict] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        result.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return result


@router.get("/api/operations/logs/{name}")
async def view_operation_log(
    name: str,
    tail_lines: int = Query(default=300, ge=1, le=2000),
) -> dict:
    path = _safe_log_path(name)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        content = "".join(deque(handle, maxlen=tail_lines))
    return {"name": path.name, "content": content}


@router.get("/api/operations/logs/{name}/download")
async def download_operation_log(name: str):
    path = _safe_log_path(name)
    return FileResponse(path, filename=path.name, media_type="text/plain")


@router.get("/api/operations/backup", response_model=OperationsConfigurationBackup)
async def export_configuration_backup(
    db: AsyncSession = Depends(get_db),
) -> OperationsConfigurationBackup:
    system = await get_or_create_system_settings(db)
    notifications = await get_or_create_notification_settings(db)
    cameras = list(await db.scalars(select(Camera).order_by(Camera.name.asc())))

    system_payload = OperationsSystemBackup(
        **{field: getattr(system, field) for field in _SYSTEM_FIELDS}
    )
    notification_payload = OperationsNotificationBackup(
        **{field: getattr(notifications, field) for field in _NOTIFICATION_FIELDS},
        recipients=[
            EmailRecipient(name=item.name, address=item.address)
            for item in parse_email_recipients(
                notifications.smtp_recipients_json,
                notifications.smtp_to,
            )
        ],
    )
    camera_payloads = [
        OperationsCameraBackup(
            **{field: getattr(camera, field) for field in _CAMERA_FIELDS}
        )
        for camera in cameras
    ]
    backup = OperationsConfigurationBackup(
        created_at=datetime.now(timezone.utc),
        system=system_payload,
        notifications=notification_payload,
        cameras=camera_payloads,
    )

    add_event(
        db,
        level="info",
        category="audit",
        code="operations.backup_exported",
        message="已导出脱敏系统配置备份",
        metadata={"camera_count": len(camera_payloads), "version": backup.version},
    )
    await db.commit()
    return backup


@router.post("/api/operations/restore", response_model=OperationsRestoreResult)
async def restore_configuration_backup(
    payload: OperationsConfigurationBackup,
    db: AsyncSession = Depends(get_db),
) -> OperationsRestoreResult:
    system = await get_or_create_system_settings(db)
    notifications = await get_or_create_notification_settings(db)

    for field in _SYSTEM_FIELDS:
        setattr(system, field, getattr(payload.system, field))
    for field in _NOTIFICATION_FIELDS:
        setattr(notifications, field, getattr(payload.notifications, field))
    notifications.smtp_recipients_json = serialize_email_recipients(payload.notifications.recipients)

    requested_names = [camera.name for camera in payload.cameras]
    existing: list[Camera] = []
    if requested_names:
        existing = list(await db.scalars(select(Camera).where(Camera.name.in_(requested_names))))
    by_name = {camera.name: camera for camera in existing}

    restored_ids: list[int] = []
    skipped: list[str] = []
    for camera_payload in payload.cameras:
        camera = by_name.get(camera_payload.name)
        if camera is None:
            skipped.append(camera_payload.name)
            continue
        for field in _CAMERA_FIELDS:
            if field == "name":
                continue
            value = getattr(camera_payload, field)
            if field == "recording_schedule":
                value = [item.model_dump() for item in value]
            setattr(camera, field, value)
        restored_ids.append(camera.id)

    add_event(
        db,
        level="info",
        category="audit",
        code="operations.backup_restored",
        message="已恢复脱敏系统配置备份",
        metadata={
            "restored_cameras": len(restored_ids),
            "skipped_cameras": skipped,
            "version": payload.version,
        },
    )
    await db.commit()

    for camera_id in restored_ids:
        recording_schedule_manager.reset_for_schedule_change(camera_id)

    return OperationsRestoreResult(
        restored_cameras=len(restored_ids),
        skipped_cameras=skipped,
    )


@router.get("/api/operations/audit", response_model=list[EventRead])
async def list_operations_audit(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.scalars(
        select(Event)
        .where(Event.category == "audit")
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(limit)
    )
    return list(rows)


def _prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    cameras = list(await db.scalars(select(Camera).order_by(Camera.id)))
    status_counts = {"online": 0, "offline": 0, "unknown": 0}
    for camera in cameras:
        status = camera.connectivity_status
        status_counts[status if status in status_counts else "unknown"] += 1

    recorder_rows = recorder_manager.status()
    running_recorders = sum(
        1
        for item in recorder_rows
        if isinstance(item, dict)
        and item.get("state") == "RECORDING"
        and item.get("pid") is not None
    )
    monitor = camera_connectivity_monitor.snapshot()

    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(settings.recordings_dir)

    lines = [
        "# HELP camera_recorder_cameras_total Configured cameras.",
        "# TYPE camera_recorder_cameras_total gauge",
        f"camera_recorder_cameras_total {len(cameras)}",
        "# HELP camera_recorder_cameras_online Cameras currently observed online.",
        "# TYPE camera_recorder_cameras_online gauge",
        f"camera_recorder_cameras_online {status_counts['online']}",
        "# HELP camera_recorder_cameras_offline Cameras currently observed offline.",
        "# TYPE camera_recorder_cameras_offline gauge",
        f"camera_recorder_cameras_offline {status_counts['offline']}",
        "# HELP camera_recorder_cameras_unknown Cameras with stale or unknown connectivity.",
        "# TYPE camera_recorder_cameras_unknown gauge",
        f"camera_recorder_cameras_unknown {status_counts['unknown']}",
        "# HELP camera_recorder_recorders_running Recorder processes currently running.",
        "# TYPE camera_recorder_recorders_running gauge",
        f"camera_recorder_recorders_running {running_recorders}",
        "# HELP camera_recorder_connectivity_monitor_errors_total Unexpected connectivity monitor cycle errors.",
        "# TYPE camera_recorder_connectivity_monitor_errors_total counter",
        f"camera_recorder_connectivity_monitor_errors_total {int(monitor.get('error_count') or 0)}",
        "# HELP camera_recorder_storage_total_bytes Total bytes on the recordings filesystem.",
        "# TYPE camera_recorder_storage_total_bytes gauge",
        f"camera_recorder_storage_total_bytes {usage.total}",
        "# HELP camera_recorder_storage_used_bytes Used bytes on the recordings filesystem.",
        "# TYPE camera_recorder_storage_used_bytes gauge",
        f"camera_recorder_storage_used_bytes {usage.used}",
        "# HELP camera_recorder_storage_free_bytes Free bytes on the recordings filesystem.",
        "# TYPE camera_recorder_storage_free_bytes gauge",
        f"camera_recorder_storage_free_bytes {usage.free}",
        "# HELP camera_recorder_connectivity_failure_streak Consecutive connectivity failures per camera.",
        "# TYPE camera_recorder_connectivity_failure_streak gauge",
    ]
    for camera in cameras:
        label = _prometheus_label(camera.name)
        lines.append(
            "camera_recorder_connectivity_failure_streak"
            f'{{camera_id="{camera.id}",camera="{label}"}} {camera.connectivity_failures}'
        )

    return PlainTextResponse(
        "\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4",
    )
