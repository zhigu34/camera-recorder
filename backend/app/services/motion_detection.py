from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class SensitivityProfile:
    var_threshold: int
    min_area_ratio: float


_PROFILES: dict[str, SensitivityProfile] = {
    "low": SensitivityProfile(var_threshold=32, min_area_ratio=0.012),
    "medium": SensitivityProfile(var_threshold=24, min_area_ratio=0.006),
    "high": SensitivityProfile(var_threshold=16, min_area_ratio=0.0025),
}


def sensitivity_profile(level: str) -> SensitivityProfile:
    try:
        return _PROFILES[level]
    except KeyError as exc:
        raise ValueError(f"unsupported motion sensitivity: {level}") from exc


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Return True when a normalized point lies inside (or on the edge of) a polygon."""

    x, y = point
    inside = False
    count = len(polygon)
    if count < 3:
        return False

    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]

        # Edge check first so points on zone borders are treated as valid motion.
        dx = x2 - x1
        dy = y2 - y1
        cross = (x - x1) * dy - (y - y1) * dx
        if abs(cross) <= 1e-9:
            if min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
                return True

        intersects = (y1 > y) != (y2 > y)
        if intersects:
            x_intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < x_intersection:
                inside = not inside

    return inside


def zones_for_point(point: tuple[float, float], zones: list[dict[str, Any]]) -> list[int | None]:
    """Return matching enabled zone IDs; no enabled zones means full-frame detection."""

    enabled = [zone for zone in zones if bool(zone.get("enabled", True))]
    if not enabled:
        return [None]

    matches: list[int | None] = []
    for zone in enabled:
        polygon = zone.get("polygon")
        if not isinstance(polygon, list):
            continue
        if point_in_polygon(point, polygon):
            zone_id = zone.get("id")
            if isinstance(zone_id, int):
                matches.append(zone_id)
    return matches


@dataclass(frozen=True, slots=True)
class ClosedMotionEvent:
    started_at: datetime
    ended_at: datetime
    zone_id: int | None
    peak_score: float


class MotionEventStateMachine:
    """Convert frame-level motion into durable events using duration and merge-gap rules."""

    def __init__(self, *, min_duration_ms: int, merge_gap_ms: int) -> None:
        self.min_duration = timedelta(milliseconds=min_duration_ms)
        self.merge_gap = timedelta(milliseconds=merge_gap_ms)
        self._candidate_started_at: datetime | None = None
        self._candidate_zone_id: int | None = None
        self._started_at: datetime | None = None
        self._zone_id: int | None = None
        self._peak_score = 0.0
        self._pending_end_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self._started_at is not None

    def _reset(self) -> None:
        self._candidate_started_at = None
        self._candidate_zone_id = None
        self._started_at = None
        self._zone_id = None
        self._peak_score = 0.0
        self._pending_end_at = None

    def _close_active(self) -> ClosedMotionEvent | None:
        if self._started_at is None:
            return None
        ended_at = self._pending_end_at or self._started_at
        event = ClosedMotionEvent(
            started_at=self._started_at,
            ended_at=ended_at,
            zone_id=self._zone_id,
            peak_score=self._peak_score,
        )
        self._reset()
        return event

    def update(
        self,
        timestamp: datetime,
        *,
        motion: bool,
        score: float,
        zone_id: int | None,
    ) -> list[ClosedMotionEvent]:
        closed: list[ClosedMotionEvent] = []

        if motion:
            if self.active and self._pending_end_at is not None:
                if timestamp - self._pending_end_at > self.merge_gap:
                    event = self._close_active()
                    if event is not None:
                        closed.append(event)
                else:
                    self._pending_end_at = None

            if self._candidate_started_at is None and not self.active:
                self._candidate_started_at = timestamp
                self._candidate_zone_id = zone_id
                self._peak_score = max(0.0, score)
            else:
                self._peak_score = max(self._peak_score, score)

            if not self.active and self._candidate_started_at is not None:
                if timestamp - self._candidate_started_at >= self.min_duration:
                    self._started_at = self._candidate_started_at
                    self._zone_id = self._candidate_zone_id
                    self._candidate_started_at = None
                    self._candidate_zone_id = None
            return closed

        if self.active:
            if self._pending_end_at is None:
                self._pending_end_at = timestamp
                return closed
            if timestamp - self._pending_end_at > self.merge_gap:
                event = self._close_active()
                if event is not None:
                    closed.append(event)
            return closed

        # Unconfirmed motion ended before the minimum duration.
        self._candidate_started_at = None
        self._candidate_zone_id = None
        self._peak_score = 0.0
        return closed
