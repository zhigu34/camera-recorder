import asyncio

from fastapi import APIRouter, Query, WebSocket
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.services.health_monitor import health_snapshot, health_trends
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule import schedule_label
from app.services.recording_schedule_manager import recording_schedule_manager
from app.services.stability_report import stability_report

router = APIRouter(tags=["health"])

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


async def _schedule_aware_snapshot() -> dict:
    """Enrich health data from the same three camera state owners used by /api/cameras."""

    snapshot = await health_snapshot()
    runtime_by_camera = {
        int(item["camera_id"]): item
        for item in recorder_manager.status()
        if isinstance(item, dict) and item.get("camera_id") is not None
    }
    async with SessionLocal() as session:
        cameras = list(await session.scalars(select(Camera).order_by(Camera.id)))

    camera_by_id = {camera.id: camera for camera in cameras}
    abnormal_count = 0
    online_count = 0
    offline_count = 0
    unknown_count = 0

    for row in snapshot.get("camera_health", []):
        camera = camera_by_id.get(int(row.get("camera_id") or 0))
        if camera is None:
            continue

        runtime = runtime_by_camera.get(camera.id, {})
        recorder_state = str(runtime.get("state") or camera.recorder_state or "STOPPED")
        connectivity_status = camera.connectivity_status
        schedule_state = recording_schedule_manager.state_for(camera)
        expected = schedule_state in _EXPECTED_RECORDING_STATES
        timestamp_warning_count = int(runtime.get("timestamp_warning_count") or 0)
        timestamp_mode = str(camera.timestamp_mode or "native")

        if camera.enabled:
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
                or (expected and recorder_state != "RECORDING")
                or runtime.get("offline_alert_active")
            )
        )

        row["connectivity_status"] = connectivity_status
        row["recorder_state"] = recorder_state
        row["schedule_state"] = schedule_state
        # Compatibility aliases for existing health clients.
        row["state"] = recorder_state
        row["expected_recording"] = expected
        row["schedule_enabled"] = camera.recording_schedule_enabled
        row["schedule_active"] = schedule_state in {"in_window", "automatic", "manual_override"}
        row["schedule"] = schedule_label(camera)
        row["abnormal"] = abnormal
        row["timestamp_mode"] = timestamp_mode
        row["timestamp_warning_count"] = timestamp_warning_count
        row["timestamp_guidance"] = _timestamp_guidance(
            timestamp_mode,
            timestamp_warning_count,
        )
        if abnormal:
            abnormal_count += 1

    cameras_summary = snapshot.setdefault("cameras", {})
    cameras_summary["abnormal"] = abnormal_count
    cameras_summary["online"] = online_count
    cameras_summary["offline"] = offline_count
    cameras_summary["unknown"] = unknown_count
    return snapshot


@router.get("/api/health/summary")
async def get_health_summary() -> dict:
    return await _schedule_aware_snapshot()


@router.get("/api/health/trends")
async def get_health_trends(
    hours: int = Query(default=24, ge=1, le=168),
    bucket_minutes: int = Query(default=60, ge=5, le=1440),
) -> dict:
    return await health_trends(hours=hours, bucket_minutes=bucket_minutes)


@router.get("/api/health/stability")
async def get_stability_report(
    hours: int = Query(default=24, ge=1, le=168),
) -> dict:
    return await stability_report(hours=hours)


@router.websocket("/ws/status")
async def status_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(
                {
                    "type": "health.snapshot",
                    "data": await _schedule_aware_snapshot(),
                }
            )
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=2.0)
            except TimeoutError:
                continue
            if message.get("type") == "websocket.disconnect":
                return
    except RuntimeError:
        # A disconnect can race with snapshot generation/send_json().
        return
