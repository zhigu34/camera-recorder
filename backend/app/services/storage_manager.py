import shutil

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.system_settings import load_runtime_settings


async def storage_snapshot() -> dict:
    async with SessionLocal() as session:
        runtime = await load_runtime_settings(session)

    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(settings.recordings_dir)
    percent = (usage.used / usage.total * 100.0) if usage.total else 0.0

    if percent >= runtime.storage_critical_percent:
        state = "critical"
    elif percent >= runtime.storage_warning_percent:
        state = "warning"
    else:
        state = "healthy"

    return {
        "path": str(settings.recordings_dir),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": round(percent, 2),
        "state": state,
        "warning_percent": runtime.storage_warning_percent,
        "critical_percent": runtime.storage_critical_percent,
    }
