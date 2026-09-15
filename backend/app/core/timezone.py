import os
from datetime import timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Shanghai"


def configured_timezone_name() -> str:
    name = os.getenv("TZ", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return "UTC"
    return name


def configured_timezone() -> tzinfo:
    name = configured_timezone_name()
    return timezone.utc if name == "UTC" else ZoneInfo(name)
