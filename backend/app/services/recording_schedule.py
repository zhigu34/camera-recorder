from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

_ALL_DAYS = list(range(7))
_DAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


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


def _days(value: Any) -> list[int]:
    # Legacy schedules did not contain a days field and therefore meant every day.
    if value is None:
        return _ALL_DAYS.copy()
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[int] = []
    for item in value:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in result:
            result.append(day)
    return sorted(result)


def normalize_windows(windows: Iterable[Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in windows or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        start = str(item.get("start") or "")
        end = str(item.get("end") or "")
        days = _days(item.get("days"))
        if _minutes(start) is None or _minutes(end) is None or start == end or not days:
            continue
        result.append({"days": days, "start": start, "end": end})
    return result


def recording_schedule_allows(camera: Any, now: datetime | None = None) -> bool:
    """Return whether the camera is inside one of its local weekly windows.

    Schedules use the deployment's local timezone (the container TZ). A disabled
    schedule preserves historical 24/7 auto-record behavior. Weekdays use Python's
    0=Monday ... 6=Sunday convention. For cross-midnight windows, the selected day
    is the day on which the window starts: Friday 22:00-06:00 continues into
    Saturday morning.
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
    weekday = local_now.weekday()
    previous_weekday = (weekday - 1) % 7

    for window in windows:
        start = _minutes(window["start"])
        end = _minutes(window["end"])
        days = window["days"]
        if start is None or end is None:
            continue
        if start < end:
            if weekday in days and start <= current < end:
                return True
        else:
            # Cross-midnight belongs to the start day. Example: Friday 22:00-06:00
            # allows Friday >=22:00 and Saturday <06:00.
            if (weekday in days and current >= start) or (
                previous_weekday in days and current < end
            ):
                return True
    return False


def _day_label(days: list[int]) -> str:
    if days == _ALL_DAYS:
        return "每天"
    if days == [0, 1, 2, 3, 4]:
        return "周一至周五"
    if days == [5, 6]:
        return "周末"
    return "/".join(_DAY_LABELS[day] for day in days)


def schedule_label(camera: Any) -> str:
    if not bool(getattr(camera, "recording_schedule_enabled", False)):
        return "全天"
    windows = normalize_windows(getattr(camera, "recording_schedule", None))
    if not windows:
        return "无时段"
    return "、".join(
        f"{_day_label(item['days'])} {item['start']}-{item['end']}" for item in windows
    )
