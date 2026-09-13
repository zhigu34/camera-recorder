from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ExportSourceSlice:
    recording_id: int
    started_at: datetime
    ended_at: datetime
    path: Path
    available: bool = True


@dataclass
class ExportInterval:
    start_at: datetime
    end_at: datetime

    @property
    def duration(self) -> float:
        return max(0.0, (self.end_at - self.start_at).total_seconds())


@dataclass
class ExportGroup(ExportInterval):
    recording_ids: list[int] = field(default_factory=list)
    sources: list[ExportSourceSlice] = field(default_factory=list)


@dataclass(frozen=True)
class ExportRangeAnalysis:
    requested_start_at: datetime
    requested_end_at: datetime
    groups: list[ExportGroup]
    gaps: list[ExportInterval]
    unavailable_intervals: list[ExportInterval]
    unavailable_count: int

    @property
    def requested_duration(self) -> float:
        return max(0.0, (self.requested_end_at - self.requested_start_at).total_seconds())

    @property
    def covered_duration(self) -> float:
        return sum(group.duration for group in self.groups)

    @property
    def recording_count(self) -> int:
        return sum(len(group.recording_ids) for group in self.groups)

    @property
    def exportable(self) -> bool:
        return bool(self.groups)


def _clip_interval(
    start: datetime,
    end: datetime,
    lower: datetime,
    upper: datetime,
) -> ExportInterval | None:
    clipped_start = max(start, lower)
    clipped_end = min(end, upper)
    if clipped_end <= clipped_start:
        return None
    return ExportInterval(clipped_start, clipped_end)


def _merge_intervals(intervals: Iterable[ExportInterval]) -> list[ExportInterval]:
    ordered = sorted(intervals, key=lambda item: (item.start_at, item.end_at))
    merged: list[ExportInterval] = []
    for item in ordered:
        if not merged or item.start_at > merged[-1].end_at:
            merged.append(item)
            continue
        previous = merged[-1]
        merged[-1] = ExportInterval(previous.start_at, max(previous.end_at, item.end_at))
    return merged


def analyze_source_slices(
    sources: Iterable[ExportSourceSlice],
    requested_start_at: datetime,
    requested_end_at: datetime,
    gap_tolerance_seconds: float = 1.0,
) -> ExportRangeAnalysis:
    if requested_end_at <= requested_start_at:
        raise ValueError("requested_end_at must be later than requested_start_at")

    tolerance = timedelta(seconds=max(0.0, gap_tolerance_seconds))
    available: list[tuple[ExportSourceSlice, ExportInterval]] = []
    unavailable: list[ExportInterval] = []
    unavailable_count = 0

    for source in sources:
        clipped = _clip_interval(
            source.started_at,
            source.ended_at,
            requested_start_at,
            requested_end_at,
        )
        if clipped is None:
            continue
        if not source.available:
            unavailable_count += 1
            unavailable.append(clipped)
            continue
        available.append((source, clipped))

    available.sort(key=lambda item: (item[1].start_at, item[1].end_at, item[0].recording_id))
    groups: list[ExportGroup] = []
    for source, clipped in available:
        if not groups or clipped.start_at > groups[-1].end_at + tolerance:
            groups.append(
                ExportGroup(
                    start_at=clipped.start_at,
                    end_at=clipped.end_at,
                    recording_ids=[source.recording_id],
                    sources=[source],
                )
            )
            continue
        group = groups[-1]
        group.end_at = max(group.end_at, clipped.end_at)
        group.recording_ids.append(source.recording_id)
        group.sources.append(source)

    gaps: list[ExportInterval] = []
    cursor = requested_start_at
    for group in groups:
        if group.start_at > cursor:
            gap = ExportInterval(cursor, group.start_at)
            if cursor == requested_start_at or gap.duration > gap_tolerance_seconds:
                gaps.append(gap)
        cursor = max(cursor, group.end_at)
    if cursor < requested_end_at:
        gaps.append(ExportInterval(cursor, requested_end_at))

    return ExportRangeAnalysis(
        requested_start_at=requested_start_at,
        requested_end_at=requested_end_at,
        groups=groups,
        gaps=gaps,
        unavailable_intervals=_merge_intervals(unavailable),
        unavailable_count=unavailable_count,
    )
