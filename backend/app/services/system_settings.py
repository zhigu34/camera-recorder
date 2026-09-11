from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret, encrypt_secret
from app.models.system_settings import SystemSettings


@dataclass(slots=True)
class RuntimeSettings:
    app_name: str = "Camera Recorder"
    segment_duration_seconds: int = 600
    remux_concurrency: int = 2
    rtsp_timeout_us: int = 5_000_000
    auto_start_enabled: bool = True
    align_segments_to_clock: bool = True
    storage_warning_percent: float = 80.0
    storage_critical_percent: float = 90.0
    upload_enabled: bool = False
    upload_concurrency: int = 2
    upload_retry_max: int = 8
    webdav_url: str = "http://openlist:5244/dav"
    webdav_root: str = "监控录像"
    webdav_username: str = "admin"
    webdav_password: str = ""
    local_retention_hours: int = 48

    @property
    def webdav_configured(self) -> bool:
        return bool(self.webdav_url.strip() and self.webdav_username.strip() and self.webdav_password)


async def get_or_create_system_settings(session: AsyncSession) -> SystemSettings:
    row = await session.get(SystemSettings, 1)
    if row is not None:
        return row
    row = SystemSettings(id=1)
    session.add(row)
    await session.flush()
    return row


async def load_runtime_settings(session: AsyncSession) -> RuntimeSettings:
    row = await session.get(SystemSettings, 1)
    if row is None:
        return RuntimeSettings()

    password = ""
    if row.webdav_password_encrypted:
        try:
            password = decrypt_secret(row.webdav_password_encrypted)
        except Exception:
            password = ""

    return RuntimeSettings(
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
        webdav_password=password,
        local_retention_hours=row.local_retention_hours,
    )


def update_webdav_password(row: SystemSettings, password: str | None, clear: bool) -> None:
    if clear:
        row.webdav_password_encrypted = None
    elif password:
        row.webdav_password_encrypted = encrypt_secret(password)