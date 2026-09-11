import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.health_monitor import health_snapshot

router = APIRouter(tags=["health"])


@router.get("/api/health/summary")
async def get_health_summary() -> dict:
    return await health_snapshot()


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
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
    except RuntimeError:
        # Starlette may raise RuntimeError if a client disconnects between
        # snapshot generation and send_json(). Treat that as a normal close.
        return
