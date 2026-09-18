import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.camera_adapter_switch import router as camera_adapter_switch_router
from app.api.camera_connections import router as camera_connections_router
from app.api.camera_discovery import router as camera_discovery_router
from app.api.cameras import router as cameras_router
from app.api.event_detection import router as event_detection_router
from app.api.events import router as events_router
from app.api.exports import router as exports_router
from app.api.health import router as health_router
from app.api.hik_cameras import router as hik_cameras_router
from app.api.hik_media import router as hik_media_router
from app.api.motion_detection import router as motion_detection_router
from app.api.notifications import router as notifications_router
from app.api.onvif_cameras import router as onvif_cameras_router
from app.api.operations import router as operations_router
from app.api.playback_control import router as playback_control_router
from app.api.playback_metrics import router as playback_metrics_router
from app.api.preview_wall import router as preview_wall_router
from app.api.recording_management import router as recording_management_router
from app.api.recording_navigation import router as recording_navigation_router
from app.api.recordings import router as recordings_router
from app.api.recorder import router as recorder_router
from app.api.settings import router as settings_router
from app.api.uploads import router as uploads_router, ws_router as uploads_ws_router
from app.core.config import settings
from app.core.database import SessionLocal, close_db, init_db
from app.core.migrations import upgrade_database
from app.services.alert_dispatcher import alert_dispatcher
from app.services.alert_monitor import alert_monitor
from app.services.camera_connectivity_monitor import camera_connectivity_monitor
from app.services.camera_identity_reconcile import reconcile_camera_form_factors
from app.services.event_log import add_event
from app.services.event_recording import event_recording_manager
from app.services.ffmpeg_capabilities import capabilities_dict
from app.services.health_sampler import health_sampler
from app.services.motion_manager import motion_detection_manager
from app.services.playback_prefetch import PlaybackPrefetchMiddleware, playback_prefetch_manager
from app.services.recorder_manager import recorder_manager
from app.services.recording_export import recording_export_manager
from app.services.recording_schedule_manager import recording_schedule_manager
from app.services.segment_processor import segment_processor
from app.services.storage_cleanup import storage_cleanup_manager
from app.services.storage_manager import storage_snapshot
from app.services.system_settings import get_or_create_system_settings
from app.services.upload_manager import upload_manager


async def _record_backend_started() -> None:
    """Persist a bounded restart marker for later recording-gap diagnosis."""

    async with SessionLocal() as session:
        add_event(
            session,
            level="info",
            category="system",
            code="system.backend_started",
            message="Camera Recorder backend 已启动",
        )
        await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    for path in (
        settings.data_dir,
        settings.data_dir / "exports",
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
        await reconcile_camera_form_factors(session)
        await session.commit()

    await _record_backend_started()
    await alert_monitor.start()
    await segment_processor.start()
    await upload_manager.start()
    await recording_export_manager.start()
    await recording_schedule_manager.start()
    await event_recording_manager.start()
    await camera_connectivity_monitor.start()
    await motion_detection_manager.start()
    await health_sampler.start()
    await storage_cleanup_manager.start()

    yield

    await playback_prefetch_manager.stop()
    await recording_export_manager.stop()
    await storage_cleanup_manager.stop()
    await health_sampler.stop()
    await motion_detection_manager.stop()
    await camera_connectivity_monitor.stop()
    await event_recording_manager.stop()
    await recording_schedule_manager.stop()
    await recorder_manager.stop_all()
    await asyncio.sleep(settings.segment_finalize_grace_seconds)
    await segment_processor.scan_once()
    await upload_manager.stop()
    await segment_processor.stop()
    await alert_monitor.stop()
    await close_db()


app = FastAPI(
    title="Camera Recorder",
    version="0.9.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PlaybackPrefetchMiddleware)

app.include_router(hik_media_router)
app.include_router(camera_connections_router)
app.include_router(camera_discovery_router)
# Keep dedicated static adapter endpoints before /api/cameras/{camera_id} routes.
app.include_router(hik_cameras_router)
app.include_router(onvif_cameras_router)
# Intercept generic updates only to switch non-RTSP cameras to manual RTSP;
# current manual RTSP updates delegate to the existing cameras handler unchanged.
app.include_router(camera_adapter_switch_router)
app.include_router(cameras_router)
app.include_router(recordings_router)
app.include_router(recording_management_router)
app.include_router(playback_control_router)
app.include_router(playback_metrics_router)
app.include_router(recording_navigation_router)
app.include_router(recorder_router)
app.include_router(uploads_router)
app.include_router(uploads_ws_router)
app.include_router(events_router)
app.include_router(notifications_router)
app.include_router(settings_router)
app.include_router(health_router)
app.include_router(preview_wall_router)
app.include_router(motion_detection_router)
app.include_router(event_detection_router)
app.include_router(exports_router)
app.include_router(operations_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system/status")
async def system_status() -> dict:
    return {
        "ffmpeg": await capabilities_dict(),
        "recorders": recorder_manager.status(),
        "recording_schedule": recording_schedule_manager.status(),
        "event_recording": event_recording_manager.status(),
        "connectivity_monitor": camera_connectivity_monitor.snapshot(),
        "segment_processor": segment_processor.status(),
        "recording_export": recording_export_manager.status(),
        "upload": await upload_manager.status(),
        "alerts": {
            "monitor": alert_monitor.status(),
            "dispatcher": alert_dispatcher.snapshot(),
        },
        "playback_prefetch": playback_prefetch_manager.snapshot(),
        "storage_cleanup": storage_cleanup_manager.status(),
        "storage": await storage_snapshot(),
    }
