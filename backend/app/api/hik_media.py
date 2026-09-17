from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.services.camera_media_session_registry import camera_media_session_registry
from app.services.hik_bridge_client import HikBridgeClient, HikBridgeClientError
from app.services.hik_media_proxy import HikRegisteredStream, HikStreamRole, build_hik_target

router = APIRouter(prefix="/internal/hik-media", tags=["internal-hik-media"])


@router.get("/{camera_id}/{role}", include_in_schema=False)
async def hik_media(camera_id: int, role: HikStreamRole):
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="camera not found")
        try:
            target = build_hik_target(camera, role)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    client = HikBridgeClient()
    try:
        stream_id = await client.create_stream(target)
    except HikBridgeClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    registered = HikRegisteredStream(client, stream_id)
    session_id = await camera_media_session_registry.register(camera_id, registered.close)

    async def registered_iter():
        try:
            async for chunk in registered.iter_bytes():
                yield chunk
        finally:
            await camera_media_session_registry.unregister(camera_id, session_id)

    return StreamingResponse(
        registered_iter(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
