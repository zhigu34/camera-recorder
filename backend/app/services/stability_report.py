import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.event import Event
from app.services.health_monitor import health_trends
from app.services.recorder_manager import recorder_manager

_FAILURE_CODES = ("camera.ffmpeg_start_failed", "camera.ffmpeg_exited")
_STREAK_CODE = "camera.ffmpeg_failure_streak"
_RESTORED_CODE = "camera.connection_restored"

_CRITERIA = {
    "min_sample_coverage": 95.0,
    "min_online_rate": 99.5,
    "min_recording_completeness": 99.5,
    "max_longest_outage_seconds": 120,
    "max_failure_streaks": 0,
    "max_ffmpeg_failures_per_24h": 3,
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


def _verdict(
    *,
    coverage: float | None,
    online_rate: float | None,
    recording_completeness: float | None,
    longest_outage_seconds: float,
    failure_streaks: int,
    ffmpeg_failures: int,
    max_ffmpeg_failures: int,
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

    event_codes = (*_FAILURE_CODES, _STREAK_CODE, _RESTORED_CODE)
    async with SessionLocal() as session:
        cameras = list(await session.scalars(select(Camera).order_by(Camera.id)))
        events = list(
            await session.scalars(
                select(Event)
                .where(Event.created_at >= cutoff, Event.code.in_(event_codes))
                .order_by(Event.created_at)
            )
        )

    events_by_camera: dict[int, list[Event]] = defaultdict(list)
    for event in events:
        if event.camera_id is not None:
            events_by_camera[event.camera_id].append(event)

    trend_by_camera = {int(row["camera_id"]): row for row in trends["cameras"]}
    camera_rows: list[dict[str, Any]] = []
    verdict_counts = {"pass": 0, "fail": 0, "collecting": 0, "ignored": 0}
    total_ffmpeg_failures = 0
    total_failure_streaks = 0
    total_outage_count = 0
    total_downtime_seconds = 0.0
    longest_outage_seconds = 0.0

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

        if monitored:
            verdict, reasons = _verdict(
                coverage=coverage,
                online_rate=online_rate,
                recording_completeness=recording_completeness,
                longest_outage_seconds=camera_longest_outage,
                failure_streaks=failure_streaks,
                ffmpeg_failures=ffmpeg_failures,
                max_ffmpeg_failures=max_ffmpeg_failures,
            )
        else:
            verdict, reasons = "ignored", []

        verdict_counts[verdict] += 1
        if monitored:
            total_ffmpeg_failures += ffmpeg_failures
            total_failure_streaks += failure_streaks
            total_outage_count += camera_outage_count
            total_downtime_seconds += camera_total_downtime
            longest_outage_seconds = max(longest_outage_seconds, camera_longest_outage)

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
            "ffmpeg_failures": total_ffmpeg_failures,
            "failure_streaks": total_failure_streaks,
            "outage_count": total_outage_count,
            "total_offline_seconds": round(total_downtime_seconds, 3),
            "longest_offline_seconds": round(longest_outage_seconds, 3),
        },
        "cameras": camera_rows,
    }
