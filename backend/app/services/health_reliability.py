from __future__ import annotations

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
from app.services.recorder_manager import recorder_manager

_FAILURE_CODES = ("camera.ffmpeg_start_failed", "camera.ffmpeg_exited")
_STREAK_CODE = "camera.ffmpeg_failure_streak"
_RESTORED_CODE = "camera.connection_restored"
_SEGMENT_FAILURE_CODE = "recording.segment_processing_failed"
_MANUAL_DELETE_CODE = "recording.deleted"
_BACKEND_STARTED_CODE = "system.backend_started"
_EVENT_CODES = (
    *_FAILURE_CODES,
    _STREAK_CODE,
    _RESTORED_CODE,
    _SEGMENT_FAILURE_CODE,
    _MANUAL_DELETE_CODE,
    _BACKEND_STARTED_CODE,
)
_MIN_RECORDING_GAP_SECONDS = 5.0
_EVENT_MATCH_PADDING_SECONDS = 60.0

GAP_CAUSE_LABELS = {
    "manual_deletion": "手动删除",
    "segment_processing_failed": "片段处理失败",
    "camera_offline": "摄像头断流",
    "ffmpeg_failure": "FFmpeg 异常",
    "recorder_unavailable": "Recorder 未处于录像状态",
    "backend_restart": "Backend 重启",
    "unknown": "未知原因",
}

CRITERIA = {
    "min_sample_coverage": 95.0,
    "min_recorder_availability_rate": 99.5,
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

    # A manual deletion is an explicit explanation and must outrank incidental
    # processing/network failures that happened near the same interval.
    for event in events:
        if event.code != _MANUAL_DELETE_CODE:
            continue
        metadata = _metadata(event)
        if str(metadata.get("reason") or "manual") != "manual":
            continue
        deleted_start = _parse_iso(metadata.get("started_at"))
        deleted_end = _parse_iso(metadata.get("ended_at"))
        if deleted_start is not None and deleted_end is not None:
            if not _overlaps(deleted_start, deleted_end, gap_start, gap_end):
                continue
        else:
            event_time = _event_created_at(event)
            if event_time is None or not padded_start <= event_time <= padded_end:
                continue
        recording_id = metadata.get("recording_id")
        suffix = f"（录像 #{recording_id}）" if recording_id else ""
        return (
            "manual_deletion",
            f"缺口对应的录像被手动删除{suffix}",
            "high",
        )

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

    # A persisted backend restart is bounded temporal evidence. It is weaker
    # than camera/FFmpeg-specific events, but stronger than a generic recorder
    # state sample because the restart itself can explain that unavailable state.
    for event in events:
        if event.code != _BACKEND_STARTED_CODE:
            continue
        created_at = _event_created_at(event)
        if created_at is not None and padded_start <= created_at <= padded_end:
            return (
                "backend_restart",
                f"缺口附近记录到 Backend 启动：{created_at.isoformat()}",
                "medium",
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
            "缺口期间没有健康采样，也未找到匹配的删除、重启、断流、FFmpeg 或片段处理失败事件",
            "low",
        )
    return (
        "unknown",
        "缺口期间 Recorder 健康采样均为 RECORDING，但未找到匹配的删除、重启、断流、FFmpeg 或片段处理失败事件",
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
                "cause_label": GAP_CAUSE_LABELS[cause],
                "detail": detail,
                "confidence": confidence,
            }
        )
    return gaps


def _verdict(
    *,
    coverage: float | None,
    recorder_availability_rate: float | None,
    recording_completeness: float | None,
    longest_outage_seconds: float,
    failure_streaks: int,
    ffmpeg_failures: int,
    max_ffmpeg_failures: int,
    recording_gap_count: int,
) -> tuple[str, list[str]]:
    if coverage is None or coverage < CRITERIA["min_sample_coverage"]:
        return "collecting", ["健康采样覆盖率不足"]
    if recorder_availability_rate is None or recording_completeness is None:
        return "collecting", ["录像/在线数据尚未完整"]

    reasons: list[str] = []
    if recorder_availability_rate < CRITERIA["min_recorder_availability_rate"]:
        reasons.append("Recorder 可用率低于验收线")
    if recording_completeness < CRITERIA["min_recording_completeness"]:
        reasons.append("录像完整率低于验收线")
    if recording_gap_count > CRITERIA["max_recording_gaps"]:
        reasons.append(f"检测到 {recording_gap_count} 个录像缺口")
    if longest_outage_seconds > CRITERIA["max_longest_outage_seconds"]:
        reasons.append("最长单次断流超过验收线")
    if failure_streaks > CRITERIA["max_failure_streaks"]:
        reasons.append("出现 FFmpeg 连续失败")
    if ffmpeg_failures > max_ffmpeg_failures:
        reasons.append("FFmpeg 异常次数超过验收线")
    return ("fail", reasons) if reasons else ("pass", [])


def camera_reliability_row(
    *,
    camera_id: int,
    name: str,
    ip: str,
    monitored: bool,
    sample_count: int,
    expected_minutes: float,
    online_samples: int,
    recording_segments: int,
    complete_segments: int,
    diagnostics: list[dict[str, Any]],
    outage_durations: list[float],
    ffmpeg_failures: int,
    failure_streaks: int,
    max_consecutive_failures: int,
    current_offline_seconds: float,
    max_ffmpeg_failures: int,
    continuous_failure_active: bool = False,
) -> dict[str, Any]:
    coverage = min(100.0, _rate(sample_count, expected_minutes) or 0.0)
    recorder_availability_rate = _rate(online_samples, sample_count)
    recording_completeness = _rate(complete_segments, recording_segments)
    longest_outage = max(outage_durations, default=0.0)
    total_offline = sum(outage_durations)
    recording_gap_count = len(diagnostics)
    missing_recording_seconds = sum(float(item.get("duration_seconds") or 0) for item in diagnostics)
    unexplained_recording_gaps = sum(1 for item in diagnostics if item.get("cause") == "unknown")
    cause_counts = Counter(str(item.get("cause") or "unknown") for item in diagnostics)

    if monitored:
        verdict, reasons = _verdict(
            coverage=coverage,
            recorder_availability_rate=recorder_availability_rate,
            recording_completeness=recording_completeness,
            longest_outage_seconds=longest_outage,
            failure_streaks=failure_streaks,
            ffmpeg_failures=ffmpeg_failures,
            max_ffmpeg_failures=max_ffmpeg_failures,
            recording_gap_count=recording_gap_count,
        )
        if cause_counts:
            summary = "、".join(
                f"{GAP_CAUSE_LABELS.get(cause, cause)} {count}" for cause, count in cause_counts.items()
            )
            reasons.append(f"缺片段原因：{summary}")
    else:
        verdict, reasons = "ignored", []

    primary_problem = None
    if diagnostics:
        diagnostic = max(
            diagnostics,
            key=lambda item: (float(item.get("duration_seconds") or 0), str(item.get("start_at") or "")),
        )
        primary_problem = {
            "kind": "recording_gap",
            "cause": diagnostic.get("cause") or "unknown",
            "detail": diagnostic.get("detail") or "录像缺口",
            "confidence": diagnostic.get("confidence") or "low",
            "started_at": diagnostic.get("start_at"),
            "ended_at": diagnostic.get("end_at"),
        }
    elif reasons:
        primary_problem = {
            "kind": "reliability",
            "cause": "reliability_degraded" if verdict == "fail" else "collecting",
            "detail": reasons[0],
            "confidence": "medium",
            "started_at": None,
            "ended_at": None,
        }

    return {
        "camera_id": camera_id,
        "name": name,
        "ip": ip,
        "monitored": monitored,
        "verdict": verdict,
        "reasons": reasons,
        "sample_coverage": round(coverage, 2),
        "observed_minutes": sample_count,
        "recorder_availability_rate": recorder_availability_rate,
        "recording_completeness": recording_completeness,
        "recording_segments": recording_segments,
        "complete_segments": complete_segments,
        "recording_gap_count": recording_gap_count,
        "missing_recording_seconds": round(missing_recording_seconds, 3),
        "unexplained_recording_gaps": unexplained_recording_gaps,
        "gap_cause_counts": dict(cause_counts),
        "diagnostics": diagnostics,
        "primary_problem": primary_problem,
        "ffmpeg_failures": ffmpeg_failures,
        "failure_streaks": failure_streaks,
        "max_consecutive_failures": max_consecutive_failures,
        "outage_count": len(outage_durations),
        "total_offline_seconds": round(total_offline, 3),
        "longest_offline_seconds": round(longest_outage, 3),
        "current_offline_seconds": round(current_offline_seconds, 3),
        "continuous_failure_active": continuous_failure_active,
    }


def _issue_for_diagnostic(camera: dict[str, Any], diagnostic: dict[str, Any]) -> dict[str, Any]:
    cause = str(diagnostic.get("cause") or "unknown")
    return {
        "kind": "recording_gap",
        "severity": "warning" if cause == "unknown" else "error",
        "camera_id": camera["camera_id"],
        "title": f"{camera['name']} 存在录像缺口",
        "detail": str(diagnostic.get("detail") or "录像时间线出现缺口"),
        "started_at": diagnostic.get("start_at"),
        "ended_at": diagnostic.get("end_at"),
        "cause": cause,
        "confidence": str(diagnostic.get("confidence") or "low"),
        "action": {
            "type": "playback",
            "camera_id": camera["camera_id"],
            "at": diagnostic.get("start_at"),
        },
    }


def _issue_for_camera(camera: dict[str, Any]) -> dict[str, Any] | None:
    if camera["verdict"] not in {"fail", "collecting"}:
        return None
    primary = camera.get("primary_problem") or {}
    return {
        "kind": "camera_reliability",
        "severity": "error" if camera["verdict"] == "fail" else "warning",
        "camera_id": camera["camera_id"],
        "title": f"{camera['name']} 可靠性{'异常' if camera['verdict'] == 'fail' else '数据收集中'}",
        "detail": str(primary.get("detail") or (camera.get("reasons") or ["可靠性数据不足"])[0]),
        "started_at": primary.get("started_at"),
        "ended_at": primary.get("ended_at"),
        "cause": str(primary.get("cause") or camera["verdict"]),
        "confidence": str(primary.get("confidence") or "medium"),
        "action": {"type": "camera", "camera_id": camera["camera_id"]},
    }


async def health_reliability(*, hours: int) -> dict[str, Any]:
    """Build the Health V3 historical read model with one bounded data-load pass."""

    if hours not in {24, 72}:
        raise ValueError("health reliability supports only 24h or 72h windows")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    runtime_rows = recorder_manager.status()
    runtime_by_camera = {
        int(item["camera_id"]): item
        for item in runtime_rows
        if isinstance(item, dict) and item.get("camera_id") is not None
    }

    async with SessionLocal() as session:
        cameras = list(await session.scalars(select(Camera).order_by(Camera.id)))
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
        events = list(
            await session.scalars(
                select(Event)
                .where(Event.created_at >= cutoff, Event.code.in_(_EVENT_CODES))
                .order_by(Event.created_at)
            )
        )

    samples_by_camera: dict[int, list[CameraHealthSample]] = defaultdict(list)
    for sample in samples:
        samples_by_camera[sample.camera_id].append(sample)

    recordings_by_camera: dict[int, list[Recording]] = defaultdict(list)
    for recording in recordings:
        recordings_by_camera[recording.camera_id].append(recording)

    events_by_camera: dict[int, list[Event]] = defaultdict(list)
    global_events: list[Event] = []
    for event in events:
        if event.camera_id is not None:
            events_by_camera[event.camera_id].append(event)
            continue
        if event.code == _SEGMENT_FAILURE_CODE:
            camera_id = int(_metadata(event).get("camera_id") or 0)
            if camera_id > 0:
                events_by_camera[camera_id].append(event)
                continue
        if event.code == _BACKEND_STARTED_CODE:
            global_events.append(event)

    max_ffmpeg_failures = max(1, int(CRITERIA["max_ffmpeg_failures_per_24h"] * hours / 24))
    camera_rows: list[dict[str, Any]] = []
    verdict_counts = {"pass": 0, "fail": 0, "collecting": 0, "ignored": 0}

    total_expected_samples = 0
    total_online_samples = 0
    total_recording_segments = 0
    total_complete_segments = 0
    total_recording_gaps = 0
    total_missing_recording_seconds = 0.0
    total_unexplained_recording_gaps = 0
    total_ffmpeg_failures = 0
    total_failure_streaks = 0
    total_outage_count = 0
    total_offline_seconds = 0.0
    longest_offline_seconds = 0.0

    for camera in cameras:
        monitored = bool(camera.enabled and camera.auto_record)
        camera_samples_all = samples_by_camera.get(camera.id, [])
        camera_samples = [sample for sample in camera_samples_all if sample.expected_recording]
        sample_count = len(camera_samples)
        online_samples = sum(1 for sample in camera_samples if sample.online)

        camera_recordings_all = recordings_by_camera.get(camera.id, [])
        camera_recordings = [
            recording
            for recording in camera_recordings_all
            if isinstance(recording.created_at, datetime) and _as_utc(recording.created_at) >= cutoff
        ]
        recording_segments = len(camera_recordings)
        complete_segments = sum(
            1
            for recording in camera_recordings
            if recording.status in {"ready", "deleted"}
            and recording.health_status == "healthy"
            and recording.ffprobe_ok == 1
            and recording.has_video == 1
        )

        camera_events = [*events_by_camera.get(camera.id, []), *global_events]
        failures = [event for event in camera_events if event.code in _FAILURE_CODES]
        streaks = [event for event in camera_events if event.code == _STREAK_CODE]
        restored = [event for event in camera_events if event.code == _RESTORED_CODE]

        outage_durations: list[float] = []
        for event in restored:
            metadata = _metadata(event)
            start = _parse_iso(metadata.get("offline_since"))
            end = _parse_iso(metadata.get("recovered_at")) or _event_created_at(event)
            if start is None or end is None:
                continue
            overlap = _clip_interval_seconds(start, end, cutoff, now)
            if overlap > 0:
                outage_durations.append(overlap)

        runtime = runtime_by_camera.get(camera.id, {})
        current_offline_seconds = 0.0
        offline_since = _parse_iso(runtime.get("offline_since"))
        if offline_since is not None:
            current_offline_seconds = _clip_interval_seconds(offline_since, now, cutoff, now)
            if current_offline_seconds > 0:
                outage_durations.append(current_offline_seconds)

        max_consecutive_failures = int(runtime.get("consecutive_failure_count") or 0)
        for event in streaks:
            max_consecutive_failures = max(
                max_consecutive_failures,
                int(_metadata(event).get("consecutive_failures") or 0),
            )

        created_at = _as_utc(camera.created_at)
        observation_start = max(cutoff, created_at)
        expected_minutes = max(1.0, (now - observation_start).total_seconds() / 60.0)
        diagnostics = (
            diagnose_recording_gaps(
                recordings=camera_recordings_all,
                samples=camera_samples_all,
                events=camera_events,
                cutoff=observation_start,
                now=now,
            )
            if monitored
            else []
        )

        row = camera_reliability_row(
            camera_id=camera.id,
            name=camera.name,
            ip=camera.ip,
            monitored=monitored,
            sample_count=sample_count,
            expected_minutes=expected_minutes,
            online_samples=online_samples,
            recording_segments=recording_segments,
            complete_segments=complete_segments,
            diagnostics=diagnostics,
            outage_durations=outage_durations,
            ffmpeg_failures=len(failures),
            failure_streaks=len(streaks),
            max_consecutive_failures=max_consecutive_failures,
            current_offline_seconds=current_offline_seconds,
            max_ffmpeg_failures=max_ffmpeg_failures,
            continuous_failure_active=bool(runtime.get("continuous_failure_active")),
        )
        camera_rows.append(row)
        verdict_counts[row["verdict"]] += 1

        if monitored:
            total_expected_samples += sample_count
            total_online_samples += online_samples
            total_recording_segments += recording_segments
            total_complete_segments += complete_segments
            total_recording_gaps += int(row["recording_gap_count"])
            total_missing_recording_seconds += float(row["missing_recording_seconds"])
            total_unexplained_recording_gaps += int(row["unexplained_recording_gaps"])
            total_ffmpeg_failures += int(row["ffmpeg_failures"])
            total_failure_streaks += int(row["failure_streaks"])
            total_outage_count += int(row["outage_count"])
            total_offline_seconds += float(row["total_offline_seconds"])
            longest_offline_seconds = max(longest_offline_seconds, float(row["longest_offline_seconds"]))

    monitored_count = sum(1 for row in camera_rows if row["monitored"])
    if verdict_counts["fail"]:
        overall_verdict = "fail"
    elif monitored_count == 0 or verdict_counts["collecting"]:
        overall_verdict = "collecting"
    else:
        overall_verdict = "pass"

    issues: list[dict[str, Any]] = []
    for camera in camera_rows:
        if camera["diagnostics"]:
            issues.extend(_issue_for_diagnostic(camera, item) for item in camera["diagnostics"])
        else:
            issue = _issue_for_camera(camera)
            if issue is not None:
                issues.append(issue)
    issues.sort(
        key=lambda item: (
            0 if item["severity"] == "error" else 1,
            item.get("started_at") or "",
            int(item.get("camera_id") or 0),
        )
    )

    return {
        "generated_at": now.isoformat(),
        "hours": hours,
        "criteria": {**CRITERIA, "max_ffmpeg_failures": max_ffmpeg_failures},
        "overall": {
            "verdict": overall_verdict,
            "monitored_cameras": monitored_count,
            "passed_cameras": verdict_counts["pass"],
            "failed_cameras": verdict_counts["fail"],
            "collecting_cameras": verdict_counts["collecting"],
            "recorder_availability_rate": _rate(total_online_samples, total_expected_samples),
            "recording_completeness": _rate(total_complete_segments, total_recording_segments),
            "recording_gap_count": total_recording_gaps,
            "missing_recording_seconds": round(total_missing_recording_seconds, 3),
            "unexplained_recording_gaps": total_unexplained_recording_gaps,
            "ffmpeg_failures": total_ffmpeg_failures,
            "failure_streaks": total_failure_streaks,
            "outage_count": total_outage_count,
            "total_offline_seconds": round(total_offline_seconds, 3),
            "longest_offline_seconds": round(longest_offline_seconds, 3),
        },
        "issues": issues,
        "cameras": camera_rows,
    }
