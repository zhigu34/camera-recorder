from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class SensitivityProfile:
    var_threshold: int
    min_area_ratio: float
    min_zone_overlap_ratio: float
    global_change_ratio: float
    global_block_ratio: float
    confidence_gain: float
    confidence_decay: float
    enter_confidence: float
    exit_confidence: float


_PROFILES: dict[str, SensitivityProfile] = {
    "low": SensitivityProfile(
        var_threshold=32,
        min_area_ratio=0.012,
        min_zone_overlap_ratio=0.35,
        global_change_ratio=0.50,
        global_block_ratio=0.75,
        confidence_gain=0.12,
        confidence_decay=0.18,
        enter_confidence=0.75,
        exit_confidence=0.20,
    ),
    "medium": SensitivityProfile(
        var_threshold=24,
        min_area_ratio=0.006,
        min_zone_overlap_ratio=0.25,
        global_change_ratio=0.60,
        global_block_ratio=0.75,
        confidence_gain=0.18,
        confidence_decay=0.14,
        enter_confidence=0.65,
        exit_confidence=0.20,
    ),
    "high": SensitivityProfile(
        var_threshold=16,
        min_area_ratio=0.0025,
        min_zone_overlap_ratio=0.15,
        global_change_ratio=0.70,
        global_block_ratio=0.75,
        confidence_gain=0.25,
        confidence_decay=0.10,
        enter_confidence=0.55,
        exit_confidence=0.15,
    ),
}


def sensitivity_profile(level: str) -> SensitivityProfile:
    try:
        return _PROFILES[level]
    except KeyError as exc:
        raise ValueError(f"unsupported motion sensitivity: {level}") from exc


@dataclass(frozen=True, slots=True)
class MotionConfidenceResult:
    motion: bool
    confidence: float
    transitioned: bool


class MotionConfidenceTracker:
    """Turn accepted frame evidence into a stable motion signal with hysteresis."""

    def __init__(self, profile: SensitivityProfile) -> None:
        self.profile = profile
        self.confidence = 0.0
        self.motion = False

    def reset(self) -> MotionConfidenceResult:
        transitioned = self.motion
        self.confidence = 0.0
        self.motion = False
        return MotionConfidenceResult(
            motion=False,
            confidence=0.0,
            transitioned=transitioned,
        )

    def update(self, raw_score: float, *, suppressed: bool = False) -> MotionConfidenceResult:
        if suppressed:
            return self.reset()

        previous_motion = self.motion
        score = min(1.0, max(0.0, raw_score))
        if score > 0.0:
            evidence_weight = 0.6 + 0.4 * score
            self.confidence += self.profile.confidence_gain * evidence_weight
        else:
            self.confidence -= self.profile.confidence_decay
        self.confidence = min(1.0, max(0.0, self.confidence))

        if self.motion:
            if self.confidence <= self.profile.exit_confidence:
                self.motion = False
        elif self.confidence >= self.profile.enter_confidence:
            self.motion = True

        return MotionConfidenceResult(
            motion=self.motion,
            confidence=self.confidence,
            transitioned=self.motion != previous_motion,
        )


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
            if (
                min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9
                and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9
            ):
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
    """Convert stable motion into durable playback-anchor events."""

    def __init__(
        self,
        *,
        min_duration_ms: int,
        merge_gap_ms: int,
        event_min_interval_ms: int = 0,
    ) -> None:
        self.min_duration = timedelta(milliseconds=min_duration_ms)
        self.merge_gap = timedelta(milliseconds=merge_gap_ms)
        self.event_min_interval = timedelta(milliseconds=event_min_interval_ms)
        self._candidate_started_at: datetime | None = None
        self._candidate_zone_id: int | None = None
        self._started_at: datetime | None = None
        self._zone_id: int | None = None
        self._peak_score = 0.0
        self._pending_started_at: datetime | None = None
        self._pending_end_at: datetime | None = None
        self._last_motion_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self._started_at is not None

    @property
    def started_at(self) -> datetime | None:
        """Return the confirmed event anchor while an event is active."""

        return self._started_at

    def _reset(self) -> None:
        self._candidate_started_at = None
        self._candidate_zone_id = None
        self._started_at = None
        self._zone_id = None
        self._peak_score = 0.0
        self._pending_started_at = None
        self._pending_end_at = None
        self._last_motion_at = None

    def _close_ready(self, timestamp: datetime) -> bool:
        if self._started_at is None or self._pending_end_at is None:
            return False
        pending_started_at = self._pending_started_at or self._pending_end_at
        return (
            timestamp - pending_started_at > self.merge_gap
            and timestamp - self._started_at >= self.event_min_interval
        )

    def _close_active(self) -> ClosedMotionEvent | None:
        if self._started_at is None:
            return None
        ended_at = self._pending_end_at or self._last_motion_at or self._started_at
        event = ClosedMotionEvent(
            started_at=self._started_at,
            ended_at=max(self._started_at, ended_at),
            zone_id=self._zone_id,
            peak_score=self._peak_score,
        )
        self._reset()
        return event

    def flush(self, timestamp: datetime) -> list[ClosedMotionEvent]:
        """Finalize confirmed motion without extending it to shutdown/reconnect time."""

        _ = timestamp
        if not self.active:
            self._reset()
            return []

        assert self._started_at is not None
        candidates = [
            boundary
            for boundary in (self._last_motion_at, self._pending_end_at)
            if boundary is not None
        ]
        ended_at = min(candidates) if candidates else self._started_at
        event = ClosedMotionEvent(
            started_at=self._started_at,
            ended_at=max(self._started_at, ended_at),
            zone_id=self._zone_id,
            peak_score=self._peak_score,
        )
        self._reset()
        return [event]

    def update(
        self,
        timestamp: datetime,
        *,
        motion: bool,
        score: float,
        zone_id: int | None,
        end_boundary_at: datetime | None = None,
    ) -> list[ClosedMotionEvent]:
        closed: list[ClosedMotionEvent] = []

        if motion:
            if self.active and self._pending_end_at is not None:
                if self._close_ready(timestamp):
                    event = self._close_active()
                    if event is not None:
                        closed.append(event)
                else:
                    # Keep one playback anchor while the minimum anchor interval is
                    # still open, even if the shorter activity merge gap elapsed.
                    self._pending_started_at = None
                    self._pending_end_at = None

            self._last_motion_at = timestamp
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
                self._pending_started_at = timestamp
                self._pending_end_at = end_boundary_at or timestamp
                return closed
            if self._close_ready(timestamp):
                event = self._close_active()
                if event is not None:
                    closed.append(event)
            return closed

        # Unconfirmed motion ended before the minimum duration.
        self._candidate_started_at = None
        self._candidate_zone_id = None
        self._peak_score = 0.0
        self._last_motion_at = None
        return closed
