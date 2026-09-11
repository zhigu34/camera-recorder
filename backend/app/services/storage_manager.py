import shutil

from app.core.config import settings


def storage_snapshot() -> dict:
    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(settings.recordings_dir)
    percent = (usage.used / usage.total * 100.0) if usage.total else 0.0

    if percent >= settings.storage_critical_percent:
        state = "critical"
    elif percent >= settings.storage_warning_percent:
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
        "warning_percent": settings.storage_warning_percent,
        "critical_percent": settings.storage_critical_percent,
    }
