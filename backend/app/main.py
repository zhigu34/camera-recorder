import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.cameras import router as cameras_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.notifications import router as notifications_router
from app.api.recorder import router as recorder_router
from app.api.recordings import router as recordings_router
from app.api.settings import router as settings_router
from app.api.uploads import router as uploads_router
from app.core.config import settings
from app.core.database import SessionLocal, close_db
from app.core.migrations import run_migrations
from app.models.camera import Camera
from app.services.alert_monitor import alert_monitor
from app.services.camera_config import runtime_config
from app.services.ffmpeg_capabilities import check_ffmpeg_capabilities
from app.services.health_sampler import health_sampler
from app.services.recorder_manager import recorder_manager
from app.services.segment_processor import segment_processor
from app.services.storage_cleanup import storage_cleanup_manager
from app.services.upload_manager import upload_manager

logger = logging.getLogger(__name__)


async def lifespan(app: FastAPI):
    run_migrations()
    capabilities = await check_ffmpeg_capabilities()
    if not capabilities["ffmpeg_available"] or not capabilities["ffprobe_available"]:
        logger.warning("ffmpeg/ffprobe unavailable; recording features are limited")
    if not capabilities["setts_available"]:
        logger.warning("ffmpeg setts bitstream filter unavailable; reconstruct mode may fail")

    await segment_processor.start()
    await upload_manager.start()
    await alert_monitor.start()

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

    # Start background observability/protection after recorder auto-start. Planned
    # startup transitions should not pollute health metrics, and cleanup must never
    # delay recorder startup.
    await health_sampler.start()
    await storage_cleanup_manager.start()

    yield

    await storage_cleanup_manager.stop()
    await health_sampler.stop()
    await recorder_manager.stop_all()
    await asyncio.sleep(settings.segment_finalize_grace_seconds)
    await segment_processor.scan_once()
    await upload_manager.stop()
    await segment_processor.stop()
    await alert_monitor.stop()
    await close_db()


app = FastAPI(
    title="Camera Recorder",
    version="0.8.3",
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
app.include_router(uploads_router)
app.include_router(events_router)
app.include_router(notifications_router)
app.include_router(settings_router)
app.include_router(health_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
