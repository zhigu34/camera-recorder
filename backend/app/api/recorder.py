from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.camera import Camera
from app.services.camera_config import runtime_config
from app.services.recorder_manager import recorder_manager

router = APIRouter(prefix="/api/recorder", tags=["recorder"])


@router.get("/status")
async def recorder_status():
    return recorder_manager.status()


@router.post("/start-all")
async def start_all(db: AsyncSession = Depends(get_db)):
    cameras = list(await db.scalars(select(Camera).where(Camera.enabled.is_(True))))
    started: list[dict] = []
    skipped: list[dict] = []
    for camera in cameras:
        if camera.timestamp_mode == "reconstruct" and (not camera.fps_num or not camera.fps_den):
            skipped.append({"camera_id": camera.id, "reason": "Probe required"})
            continue
        started.append(await recorder_manager.start(runtime_config(camera)))
        camera.status = "recording"
    await db.commit()
    return {"started": started, "skipped": skipped}


@router.post("/stop-all")
async def stop_all(db: AsyncSession = Depends(get_db)):
    await recorder_manager.stop_all()
    cameras = list(await db.scalars(select(Camera)))
    for camera in cameras:
        if camera.status == "recording":
            camera.status = "stopped"
    await db.commit()
    return {"status": "stopped"}
