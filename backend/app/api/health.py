import asyncio

from fastapi import APIRouter, Query, WebSocket

from app.services.health_monitor import health_snapshot, health_trends
from app.services.stability_report import stability_report

router = APIRouter(tags=["health"])


@router.get("/api/health/summary")
async def get_health_summary() -> dict:
    return await health_snapshot()


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
                    "data": await health_snapshot(),
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
