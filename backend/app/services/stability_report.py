import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.event import Event
from app.models.health_sample import CameraHealthSample
from app.models.recording import Recording
from app.services.health_monitor import health_trends
from app.services.recorder_manager import recorder_manager

_FAILURE_CODES = ("camera.ffmpeg_start_failed", "camera.ffmpeg_exited")
_STREAK_CODE = "camera.ffmpeg_failure_streak"
_RESTORED_CODE = "camera.connection_restored"
_SEGMENT_FAILURE_CODE = "recording.segment_processing_failed"
_MIN_RECORDING_GAP_SECONDS = 5.0
_EVENT_MATCH_PADDING_SECONDS = 60.0

_GAP_CAUSE_LABELS = {
    "segment_processing_failed": "片段处理失败",
    "camera_offline": "摄像头断流",
    "ffmpeg_failure": "FFmpeg 异常",
    "recorder_unavailable": "Recorder 未处于录像状态",
    "unknown": "未知原因",
}

_CRITERIA = {
    "min_sample_coverage": 95.0,
    "min_online_rate": 99.5,
    "min_recording_completeness": 99.5,
    "max_longest_outage_seconds": 120,
    "max_failure_streaks": 0,
    "max_ffmpeg_failures_per_24h": 3,
    "max_recording_gaps": 0,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _metadata(event: Event) -> dict[str, Any]:
    if not event.metadata_json:
        return {}
    try:
        value = json.loads(event.metadata_json)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _rate(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 2)


def _clip_interval_seconds(
    start: datetime,
    end: datetime,
    cutoff: datetime,
    now: datetime,
) -> float:
    left = max(_as_utc(start), cutoff)
    right = min(_as_utc(end), now)
    return max(0.0, (right - left).total_seconds())


def _recording_interval(recording: Recording) -> tuple[datetime, datetime] | None:
    started_at = getattr(recording, "started_at", None)
    if not isinstance(started_at, datetime):
        return None
    start = _as_utc(started_at)
    ended_at = getattr(recording, "ended_at", None)
    if isinstance(ended_at, datetime):
        end = _as_utc(ended_at)
    else:
        duration = float(getattr(recording, "duration", 0) or 0)
        if duration <= 0:
            return None
        end = start + timedelta(seconds=duration)
    return (start, end) if end > start else None


def _event_created_at(event: Event) -> datetime | None:
    created_at = getattr(event, "created_at", None)
    return _as_utc(created_at) if isinstance(created_at, datetime) else None


def _overlaps(start: datetime, end: datetime, left: datetime, right: datetime) -> bool:
    return start < right and end > left


def _diagnose_gap_cause(
    *,
    gap_start: datetime,
    gap_end: datetime,
    samples: list[CameraHealthSample],
    events: list[Event],
) -> tuple[str, str, str] | None:
    gap_samples = [
        sample
        for sample in samples
        if isinstance(getattr(sample, "sampled_at", None), datetime)
        and gap_start <= _as_utc(sample.sampled_at) < gap_end
    ]
    expected_samples = [sample for sample in gap_samples if bool(sample.expected_recording)]
    if gap_samples and not expected_samples:
        return None

    padded_start = gap_start - timedelta(seconds=_EVENT_MATCH_PADDING_SECONDS)
    padded_end = gap_end + timedelta(seconds=_EVENT_MATCH_PADDING_SECONDS)

    for event in events:
        if event.code != _SEGMENT_FAILURE_CODE:
            continue
        metadata = _metadata(event)
        segment_started_at = _parse_iso(metadata.get("segment_started_at"))
        event_time = segment_started_at or _event_created_at(event)
        if event_time is None or not padded_start <= event_time <= padded_end:
            continue
        stage = str(metadata.get("stage") or "process")
        reason = str(metadata.get("reason") or "未提供底层错误")
        return (
            "segment_processing_failed",
            f"录像片段在 {stage} 阶段处理失败：{reason}",
            "high",
        )

    for event in events:
        if event.code != _RESTORED_CODE:
            continue
        metadata = _metadata(event)
        offline_since = _parse_iso(metadata.get("offline_since"))
        recovered_at = _parse_iso(metadata.get("recovered_at")) or _event_created_at(event)
        if offline_since is not None and recovered_at is not None and _overlaps(
            offline_since, recovered_at, gap_start, gap_end
        ):
            return (
                "camera_offline",
                f"缺口与摄像头断流重叠：{offline_since.isoformat()} 至 {recovered_at.isoformat()}",
                "high",
            )

    for event in events:
        if event.code not in _FAILURE_CODES:
            continue
        created_at = _event_created_at(event)
        if created_at is not None and padded_start <= created_at <= padded_end:
            return (
                "ffmpeg_failure",
                f"缺口附近记录到 FFmpeg 异常事件 {event.code}",
                "high",
            )

    unavailable = [
        sample
        for sample in expected_samples
        if sample.state != "RECORDING" or sample.recorder_ok is False
    ]
    if unavailable:
        states = sorted({str(sample.state) for sample in unavailable})
        return (
            "recorder_unavailable",
            f"缺口期间 Recorder 健康采样异常：{', '.join(states)}",
            "medium",
        )

    if not gap_samples:
        return (
            "unknown",
            "缺口期间没有健康采样，也未找到匹配的断流、FFmpeg 或片段处理失败事件",
            "low",
        )
    return (
        "unknown",
        "缺口期间 Recorder 健康采样均为 RECORDING，但未找到匹配的断流、FFmpeg 或片段处理失败事件",
        "low",
    )


def diagnose_recording_gaps(
    *,
    recordings: list[Recording],
    samples: list[CameraHealthSample],
    events: list[Event],
    cutoff: datetime,
    now: datetime,
    min_gap_seconds: float = _MIN_RECORDING_GAP_SECONDS,
) -> list[dict[str, Any]]:
    """Diagnose meaningful holes between adjacent playable recording intervals.

    Planned non-recording windows are ignored when historical health samples
    explicitly say recording was not expected. Every counted gap receives a
    concrete cause/detail/confidence tuple; unknown is explicit rather than blank.
    """

    cutoff = _as_utc(cutoff)
    now = _as_utc(now)
    intervals: list[tuple[datetime, datetime]] = []
    for recording in recordings:
        interval = _recording_interval(recording)
        if interval is None:
            continue
        start, end = interval
        start = max(start, cutoff)
        end = min(end, now)
        if end > start:
            intervals.append((start, end))
    intervals.sort(key=lambda item: item[0])
    if len(intervals) < 2:
        return []

    merged: list[list[datetime]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    gaps: list[dict[str, Any]] = []
    threshold = max(0.0, float(min_gap_seconds))
    for index in range(len(merged) - 1):
        gap_start = merged[index][1]
        gap_end = merged[index + 1][0]
        duration_seconds = (gap_end - gap_start).total_seconds()
        if duration_seconds < threshold:
            continue
        diagnosis = _diagnose_gap_cause(
            gap_start=gap_start,
            gap_end=gap_end,
            samples=samples,
            events=events,
        )
        if diagnosis is None:
            continue
        cause, detail, confidence = diagnosis
        gaps.append(
            {
                "start_at": gap_start.isoformat(),
                "end_at": gap_end.isoformat(),
                "duration_seconds": round(duration_seconds, 3),
                "cause": cause,
                "cause_label": _GAP_CAUSE_LABELS[cause],
                "detail": detail,
                "confidence": confidence,
            }
        )
    return gaps


def _verdict(
    *,
    coverage: float | None,
    online_rate: float | None,
    recording_completeness: float | None,
    longest_outage_seconds: float,
    failure_streaks: int,
    ffmpeg_failures: int,
    max_ffmpeg_failures: int,
    recording_gap_count: int,
) -> tuple[str, list[str]]:
    if coverage is None or coverage < _CRITERIA["min_sample_coverage"]:
        return "collecting", ["健康采样覆盖率不足"]
    if online_rate is None or recording_completeness is None:
        return "collecting", ["录像/在线数据尚未完整"]

    reasons: list[str] = []
    if online_rate < _CRITERIA["min_online_rate"]:
        reasons.append("在线率低于验收线")
    if recording_completeness < _CRITERIA["min_recording_completeness"]:
        reasons.append("录像完整率低于验收线")
    if recording_gap_count > _CRITERIA["max_recording_gaps"]:
        reasons.append(f"检测到 {recording_gap_count} 个录像缺口")
    if longest_outage_seconds > _CRITERIA["max_longest_outage_seconds"]:
        reasons.append("最长单次断流超过验收线")
    if failure_streaks > _CRITERIA["max_failure_streaks"]:
        reasons.append("出现 FFmpeg 连续失败")
    if ffmpeg_failures > max_ffmpeg_failures:
        reasons.append("FFmpeg 异常次数超过验收线")
    return ("fail", reasons) if reasons else ("pass", [])


async def stability_report(*, hours: int = 24) -> dict[str, Any]:
    """Build a 24h/72h-oriented acceptance report from samples and exact events."""

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    trends = await health_trends(hours=hours, bucket_minutes=60)
    runtime_rows = recorder_manager.status()
    runtime_by_camera = {
        int(item["camera_id"]): item
        for item in runtime_rows
        if isinstance(item, dict) and item.get("camera_id") is not None
    }

    event_codes = (*_FAILURE_CODES, _STREAK_CODE, _RESTORED_CODE, _SEGMENT_FAILURE_CODE)
    async with SessionLocal() as session:
        cameras = list(await session.scalars(select(Camera).order_by(Camera.id)))
        events = list(
            await session.scalars(
                select(Event)
                .where(Event.created_at >= cutoff, Event.code.in_(event_codes))
                .order_by(Event.created_at)
            )
        )
        samples = list(
            await session.scalars(
                select(CameraHealthSample)
                .where(CameraHealthSample.sampled_at >= cutoff)
                .order_by(CameraHealthSample.sampled_at)
            )
        )
        recordings = list(
            await session.scalars(
                select(Recording)
                .where(
                    Recording.started_at >= cutoff - timedelta(hours=1),
                    Recording.started_at <= now,
                )
                .order_by(Recording.camera_id, Recording.started_at)
            )
        )

    events_by_camera: dict[int, list[Event]] = defaultdict(list)
    for event in events:
        if event.camera_id is not None:
            events_by_camera[event.camera_id].append(event)
        elif event.code == _SEGMENT_FAILURE_CODE:
            metadata_camera_id = int(_metadata(event).get("camera_id") or 0)
            if metadata_camera_id > 0:
                events_by_camera[metadata_camera_id].append(event)

    samples_by_camera: dict[int, list[CameraHealthSample]] = defaultdict(list)
    for sample in samples:
        samples_by_camera[sample.camera_id].append(sample)
    recordings_by_camera: dict[int, list[Recording]] = defaultdict(list)
    for recording in recordings:
        recordings_by_camera[recording.camera_id].append(recording)

    trend_by_camera = {int(row["camera_id"]): row for row in trends["cameras"]}
    camera_rows: list[dict[str, Any]] = []
    verdict_counts = {"pass": 0, "fail": 0, "collecting": 0, "ignored": 0}
    total_ffmpeg_failures = 0
    total_failure_streaks = 0
    total_outage_count = 0
    total_downtime_seconds = 0.0
    longest_outage_seconds = 0.0
    total_recording_gaps = 0
    total_missing_recording_seconds = 0.0
    total_unexplained_recording_gaps = 0

    max_ffmpeg_failures = max(
        1,
        int(_CRITERIA["max_ffmpeg_failures_per_24h"] * hours / 24),
    )

    for camera in cameras:
        trend = trend_by_camera.get(camera.id, {})
        monitored = bool(camera.enabled and camera.auto_record)
        runtime = runtime_by_camera.get(camera.id, {})
        camera_events = events_by_camera.get(camera.id, [])

        failures = [event for event in camera_events if event.code in _FAILURE_CODES]
        streaks = [event for event in camera_events if event.code == _STREAK_CODE]
        restored = [event for event in camera_events if event.code == _RESTORED_CODE]

        outage_durations: list[float] = []
        for event in restored:
            metadata = _metadata(event)
            start = _parse_iso(metadata.get("offline_since"))
            end = _parse_iso(metadata.get("recovered_at")) or _as_utc(event.created_at)
            if start is None:
                continue
            overlap = _clip_interval_seconds(start, end, cutoff, now)
            if overlap > 0:
                outage_durations.append(overlap)

        current_offline_seconds = 0.0
        offline_since = _parse_iso(runtime.get("offline_since"))
        if offline_since is not None:
            current_offline_seconds = _clip_interval_seconds(offline_since, now, cutoff, now)
            if current_offline_seconds > 0:
                outage_durations.append(current_offline_seconds)

        max_streak = int(runtime.get("consecutive_failure_count") or 0)
        for event in streaks:
            metadata = _metadata(event)
            max_streak = max(max_streak, int(metadata.get("consecutive_failures") or 0))

        created_at = _as_utc(camera.created_at)
        observation_start = max(cutoff, created_at)
        expected_minutes = max(1.0, (now - observation_start).total_seconds() / 60.0)
        sample_count = int(trend.get("samples") or 0)
        coverage = min(100.0, _rate(sample_count, expected_minutes) or 0.0)

        online_rate = trend.get("online_rate")
        recording_completeness = trend.get("recording_completeness")
        camera_longest_outage = max(outage_durations, default=0.0)
        camera_total_downtime = sum(outage_durations)
        camera_outage_count = len(outage_durations)
        ffmpeg_failures = len(failures)
        failure_streaks = len(streaks)
        gap_diagnostics = diagnose_recording_gaps(
            recordings=recordings_by_camera.get(camera.id, []),
            samples=samples_by_camera.get(camera.id, []),
            events=camera_events,
            cutoff=observation_start,
            now=now,
        ) if monitored else []
        recording_gap_count = len(gap_diagnostics)
        missing_recording_seconds = sum(float(item["duration_seconds"]) for item in gap_diagnostics)
        unexplained_recording_gaps = sum(1 for item in gap_diagnostics if item["cause"] == "unknown")
        gap_cause_counts = Counter(str(item["cause"]) for item in gap_diagnostics)

        if monitored:
            verdict, reasons = _verdict(
                coverage=coverage,
                online_rate=online_rate,
                recording_completeness=recording_completeness,
                longest_outage_seconds=camera_longest_outage,
                failure_streaks=failure_streaks,
                ffmpeg_failures=ffmpeg_failures,
                max_ffmpeg_failures=max_ffmpeg_failures,
                recording_gap_count=recording_gap_count,
            )
            if gap_cause_counts:
                summary = "、".join(
                    f"{_GAP_CAUSE_LABELS[cause]} {count}"
                    for cause, count in gap_cause_counts.items()
                )
                reasons.append(f"缺片段原因：{summary}")
        else:
            verdict, reasons = "ignored", []

        verdict_counts[verdict] += 1
        if monitored:
            total_ffmpeg_failures += ffmpeg_failures
            total_failure_streaks += failure_streaks
            total_outage_count += camera_outage_count
            total_downtime_seconds += camera_total_downtime
            longest_outage_seconds = max(longest_outage_seconds, camera_longest_outage)
            total_recording_gaps += recording_gap_count
            total_missing_recording_seconds += missing_recording_seconds
            total_unexplained_recording_gaps += unexplained_recording_gaps

        camera_rows.append(
            {
                "camera_id": camera.id,
                "name": camera.name,
                "ip": camera.ip,
                "monitored": monitored,
                "verdict": verdict,
                "reasons": reasons,
                "sample_coverage": round(coverage, 2),
                "observed_minutes": sample_count,
                "online_rate": online_rate,
                "recording_completeness": recording_completeness,
                "recording_segments": int(trend.get("recording_segments") or 0),
                "complete_segments": int(trend.get("complete_segments") or 0),
                "recording_gap_count": recording_gap_count,
                "missing_recording_seconds": round(missing_recording_seconds, 3),
                "unexplained_recording_gaps": unexplained_recording_gaps,
                "gap_cause_counts": dict(gap_cause_counts),
                "gap_diagnostics": gap_diagnostics,
                "ffmpeg_failures": ffmpeg_failures,
                "failure_streaks": failure_streaks,
                "max_consecutive_failures": max_streak,
                "outage_count": camera_outage_count,
                "total_offline_seconds": round(camera_total_downtime, 3),
                "longest_offline_seconds": round(camera_longest_outage, 3),
                "current_offline_seconds": round(current_offline_seconds, 3),
                "continuous_failure_active": bool(runtime.get("continuous_failure_active")),
            }
        )

    monitored_count = sum(1 for row in camera_rows if row["monitored"])
    if verdict_counts["fail"]:
        overall_verdict = "fail"
    elif monitored_count == 0 or verdict_counts["collecting"]:
        overall_verdict = "collecting"
    else:
        overall_verdict = "pass"

    return {
        "generated_at": now.isoformat(),
        "hours": hours,
        "criteria": {
            **_CRITERIA,
            "max_ffmpeg_failures": max_ffmpeg_failures,
        },
        "overall": {
            "verdict": overall_verdict,
            "monitored_cameras": monitored_count,
            "passed_cameras": verdict_counts["pass"],
            "failed_cameras": verdict_counts["fail"],
            "collecting_cameras": verdict_counts["collecting"],
            "online_rate": trends["overall"]["online_rate"],
            "recording_completeness": trends["overall"]["recording_completeness"],
            "recording_gap_count": total_recording_gaps,
            "missing_recording_seconds": round(total_missing_recording_seconds, 3),
            "unexplained_recording_gaps": total_unexplained_recording_gaps,
            "ffmpeg_failures": total_ffmpeg_failures,
            "failure_streaks": total_failure_streaks,
            "outage_count": total_outage_count,
            "total_offline_seconds": round(total_downtime_seconds, 3),
            "longest_offline_seconds": round(longest_outage_seconds, 3),
        },
        "cameras": camera_rows,
    }
