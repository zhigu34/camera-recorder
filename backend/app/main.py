import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.cameras import router as cameras_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.notifications import router as notifications_router
from app.api.recordings import router as recordings_router
from app.api.recorder import router as recorder_router
from app.api.settings import router as settings_router
from app.api.uploads import router as uploads_router
from app.core.config import settings
from app.core.database import SessionLocal, close_db, init_db
from app.core.migrations import upgrade_database
from app.models.camera import Camera
from app.services.alert_dispatcher import alert_dispatcher
from app.services.alert_monitor import alert_monitor
from app.services.camera_config import runtime_config
from app.services.ffmpeg_capabilities import capabilities_dict
from app.services.health_sampler import health_sampler
from app.services.recorder_manager import recorder_manager
from app.services.segment_processor import segment_processor
from app.services.storage_cleanup import storage_cleanup_manager
from app.services.storage_manager import storage_snapshot
from app.services.system_settings import get_or_create_system_settings, load_runtime_settings
from app.services.upload_manager import upload_manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    for path in (
        settings.data_dir,
        settings.recordings_dir,
        settings.staging_dir,
        settings.failed_dir,
        settings.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    await upgrade_database()
    await init_db()

    async with SessionLocal() as session:
        await get_or_create_system_settings(session)
        await session.commit()
        runtime = await load_runtime_settings(session)

    # Start the alert observer before background workers/recorders so new failure
    # events are never missed. It only reads state/events and cannot block recording.
    await alert_monitor.start()
    await segment_processor.start()
    await upload_manager.start()

    if runtime.auto_start_enabled:
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
    version="0.8.2",
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
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system/status")
async def system_status() -> dict:
    async with SessionLocal() as session:
        runtime = await load_runtime_settings(session)
    upload = await upload_manager.status()
    return {
        "app": runtime.app_name,
        "segment_duration_seconds": runtime.segment_duration_seconds,
        "ffmpeg": await capabilities_dict(),
        "recorders": recorder_manager.status(),
        "upload": upload,
        "storage": await storage_snapshot(),
        "storage_cleanup": storage_cleanup_manager.status(),
        "alerts": {
            "monitor": alert_monitor.status(),
            "dispatcher": alert_dispatcher.snapshot(),
        },
    }


@app.get("/api/system/storage")
async def system_storage() -> dict:
    snapshot = await storage_snapshot()
    snapshot["cleanup"] = storage_cleanup_manager.status()
    return snapshot
