from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


def _minutes(value: str) -> int | None:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (AttributeError, TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def normalize_windows(windows: Iterable[Any] | None) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in windows or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        start = str(item.get("start") or "")
        end = str(item.get("end") or "")
        if _minutes(start) is None or _minutes(end) is None or start == end:
            continue
        result.append({"start": start, "end": end})
    return result


def recording_schedule_allows(camera: Any, now: datetime | None = None) -> bool:
    """Return whether the camera is inside one of its local recording windows.

    Schedules use the deployment's local timezone (the container TZ). A disabled
    schedule preserves the historical behavior: auto-record is allowed all day.
    Windows may cross midnight, e.g. 22:00 -> 06:00.
    """

    if not bool(getattr(camera, "recording_schedule_enabled", False)):
        return True

    windows = normalize_windows(getattr(camera, "recording_schedule", None))
    if not windows:
        return False

    local_now = now or datetime.now().astimezone()
    if local_now.tzinfo is None:
        local_now = local_now.astimezone()
    else:
        local_now = local_now.astimezone()
    current = local_now.hour * 60 + local_now.minute

    for window in windows:
        start = _minutes(window["start"])
        end = _minutes(window["end"])
        if start is None or end is None:
            continue
        if start < end:
            if start <= current < end:
                return True
        else:
            # Cross-midnight: 22:00-06:00 means [22:00, 24:00) U [00:00, 06:00).
            if current >= start or current < end:
                return True
    return False


def schedule_label(camera: Any) -> str:
    if not bool(getattr(camera, "recording_schedule_enabled", False)):
        return "全天"
    windows = normalize_windows(getattr(camera, "recording_schedule", None))
    if not windows:
        return "无时段"
    return "、".join(f"{item['start']}-{item['end']}" for item in windows)
