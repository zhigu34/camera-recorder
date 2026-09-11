import asyncio
from datetime import datetime

from fastapi import APIRouter, Query, WebSocket
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.services.health_monitor import health_snapshot, health_trends
from app.services.recorder_manager import recorder_manager
from app.services.recording_schedule import recording_schedule_allows, schedule_label
from app.services.stability_report import stability_report
from app.services.system_settings import load_runtime_settings

router = APIRouter(tags=["health"])


async def _schedule_aware_snapshot() -> dict:
    snapshot = await health_snapshot()
    local_now = datetime.now().astimezone()
    runtime_by_camera = {
        int(item["camera_id"]): item
        for item in recorder_manager.status()
        if isinstance(item, dict) and item.get("camera_id") is not None
    }
    async with SessionLocal() as session:
        runtime_settings = await load_runtime_settings(session)
        cameras = list(await session.scalars(select(Camera).order_by(Camera.id)))

    camera_by_id = {camera.id: camera for camera in cameras}
    abnormal_count = 0
    for row in snapshot.get("camera_health", []):
        camera = camera_by_id.get(int(row.get("camera_id") or 0))
        if camera is None:
            continue
        in_window = recording_schedule_allows(camera, local_now)
        expected = bool(
            runtime_settings.auto_start_enabled
            and camera.enabled
            and camera.auto_record
            and in_window
        )
        runtime = runtime_by_camera.get(camera.id, {})
        state = str(row.get("state") or "STOPPED")
        abnormal = bool(
            (expected and state != "RECORDING")
            or runtime.get("offline_alert_active")
        )
        row["expected_recording"] = expected
        row["schedule_enabled"] = camera.recording_schedule_enabled
        row["schedule_active"] = in_window
        row["schedule"] = schedule_label(camera)
        row["abnormal"] = abnormal
        if abnormal:
            abnormal_count += 1

    snapshot.setdefault("cameras", {})["abnormal"] = abnormal_count
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
