import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.cameras import router as cameras_router
from app.api.recordings import router as recordings_router
from app.api.recorder import router as recorder_router
from app.core.config import settings
from app.core.database import SessionLocal, close_db, init_db
from app.models.camera import Camera
from app.services.camera_config import runtime_config
from app.services.ffmpeg_capabilities import capabilities_dict
from app.services.recorder_manager import recorder_manager
from app.services.segment_processor import segment_processor


@asynccontextmanager
async def lifespan(_: FastAPI):
    for path in (
        settings.recordings_dir,
        settings.staging_dir,
        settings.failed_dir,
        settings.logs_dir,
        settings.database_url.startswith("sqlite") and settings.recordings_dir.parent / "data",
    ):
        if path:
            path.mkdir(parents=True, exist_ok=True)

    await init_db()
    await segment_processor.start()

    if settings.auto_start_enabled:
        async with SessionLocal() as session:
            cameras = list(
                await session.scalars(
                    select(Camera).where(
                        Camera.enabled.is_(True),
                        Camera.auto_record.is_(True),
                    )
                )
            )
            for camera in cameras:
                if camera.timestamp_mode == "reconstruct" and (
                    not camera.fps_num or not camera.fps_den
                ):
                    continue
                await recorder_manager.start(runtime_config(camera))
                camera.status = "recording"
            await session.commit()

    yield

    await recorder_manager.stop_all()
    await asyncio.sleep(settings.segment_finalize_grace_seconds)
    await segment_processor.scan_once()
    await segment_processor.stop()
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cameras_router)
app.include_router(recordings_router)
app.include_router(recorder_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system/status")
async def system_status() -> dict:
    return {
        "app": settings.app_name,
        "segment_duration_seconds": settings.segment_duration_seconds,
        "ffmpeg": await capabilities_dict(),
        "recorders": recorder_manager.status(),
    }
