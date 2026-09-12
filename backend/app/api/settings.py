from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.system_settings import SystemSettings
from app.schemas.system_settings import SystemSettingsRead, SystemSettingsUpdate
from app.services.event_log import add_event
from app.services.system_settings import (
    get_or_create_system_settings,
    load_runtime_settings,
    update_webdav_password,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _serialize(row: SystemSettings) -> SystemSettingsRead:
    return SystemSettingsRead(
        app_name=row.app_name,
        segment_duration_seconds=row.segment_duration_seconds,
        remux_concurrency=row.remux_concurrency,
        rtsp_timeout_us=row.rtsp_timeout_us,
        auto_start_enabled=row.auto_start_enabled,
        align_segments_to_clock=row.align_segments_to_clock,
        storage_warning_percent=row.storage_warning_percent,
        storage_critical_percent=row.storage_critical_percent,
        upload_enabled=row.upload_enabled,
        upload_concurrency=row.upload_concurrency,
        upload_retry_max=row.upload_retry_max,
        webdav_url=row.webdav_url,
        webdav_root=row.webdav_root,
        webdav_username=row.webdav_username,
        webdav_password_set=bool(row.webdav_password_encrypted),
        local_retention_hours=row.local_retention_hours,
        openlist_management_port=settings.openlist_public_port,
    )


@router.get("", response_model=SystemSettingsRead)
async def get_settings(db: AsyncSession = Depends(get_db)):
    row = await get_or_create_system_settings(db)
    await db.commit()
    return _serialize(row)


@router.put("", response_model=SystemSettingsRead)
async def update_settings(
    payload: SystemSettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_system_settings(db)
    row.app_name = payload.app_name.strip()
    row.segment_duration_seconds = payload.segment_duration_seconds
    row.remux_concurrency = payload.remux_concurrency
    row.rtsp_timeout_us = payload.rtsp_timeout_us
    row.auto_start_enabled = payload.auto_start_enabled
    row.align_segments_to_clock = payload.align_segments_to_clock
    row.storage_warning_percent = payload.storage_warning_percent
    row.storage_critical_percent = payload.storage_critical_percent
    row.upload_enabled = payload.upload_enabled
    row.upload_concurrency = payload.upload_concurrency
    row.upload_retry_max = payload.upload_retry_max
    row.webdav_url = payload.webdav_url.strip().rstrip("/")
    row.webdav_root = payload.webdav_root.strip("/")
    row.webdav_username = payload.webdav_username.strip()
    row.local_retention_hours = payload.local_retention_hours
    update_webdav_password(row, payload.webdav_password, payload.clear_webdav_password)

    add_event(
        db,
        level="info",
        category="system",
        code="system.settings_updated",
        message="系统运行参数已更新",
    )
    await db.commit()
    await db.refresh(row)
    return _serialize(row)


@router.get("/runtime")
async def runtime_settings(db: AsyncSession = Depends(get_db)) -> dict:
    cfg = await load_runtime_settings(db)
    return {
        "app_name": cfg.app_name,
        "upload_enabled": cfg.upload_enabled,
        "webdav_configured": cfg.webdav_configured,
        "segment_duration_seconds": cfg.segment_duration_seconds,
    }
