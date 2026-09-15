from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.camera import Camera
from app.models.event import Event
from app.models.health_sample import CameraHealthSample
from app.models.recording import Recording
from app.services.health_reliability import (
    CRITERIA,
    _BACKEND_STARTED_CODE,
    _EVENT_CODES,
    _FAILURE_CODES,
    _RESTORED_CODE,
    _SEGMENT_FAILURE_CODE,
    _STREAK_CODE,
    _as_utc,
    _clip_interval_seconds,
    _event_created_at,
    _metadata,
    _parse_iso,
    _rate,
    camera_reliability_row,
    diagnose_recording_gaps,
)
from app.services.recorder_manager import recorder_manager


async def build_health_reliability_report(*, hours: int) -> dict[str, Any]:
    """Build legacy-window reliability data with one bounded history load.

    V3 exposes only 24h/72h, while the compatibility stability endpoint and CLI
    historically accept 1-168h. This builder keeps that wider window without
    nesting health_trends() or another high-level report, while reusing the V3
    verdict/gap calculation primitives so the two paths do not diverge in rules.
    """

    if not 1 <= hours <= 168:
        raise ValueError("stability window must be between 1 and 168 hours")

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

        observation_start = max(cutoff, _as_utc(camera.created_at))
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
        "cameras": camera_rows,
    }


async def stability_report(*, hours: int = 24) -> dict[str, Any]:
    """Compatibility adapter for the legacy stability API and CLI contract."""

    report = await build_health_reliability_report(hours=hours)
    overall = report["overall"]
    cameras = []
    for camera in report["cameras"]:
        cameras.append(
            {
                "camera_id": camera["camera_id"],
                "name": camera["name"],
                "ip": camera["ip"],
                "monitored": camera["monitored"],
                "verdict": camera["verdict"],
                "reasons": camera["reasons"],
                "sample_coverage": camera["sample_coverage"],
                "observed_minutes": camera["observed_minutes"],
                "online_rate": camera["recorder_availability_rate"],
                "recording_completeness": camera["recording_completeness"],
                "recording_segments": camera["recording_segments"],
                "complete_segments": camera["complete_segments"],
                "recording_gap_count": camera["recording_gap_count"],
                "missing_recording_seconds": camera["missing_recording_seconds"],
                "unexplained_recording_gaps": camera["unexplained_recording_gaps"],
                "gap_cause_counts": camera["gap_cause_counts"],
                "gap_diagnostics": camera["diagnostics"],
                "ffmpeg_failures": camera["ffmpeg_failures"],
                "failure_streaks": camera["failure_streaks"],
                "max_consecutive_failures": camera["max_consecutive_failures"],
                "outage_count": camera["outage_count"],
                "total_offline_seconds": camera["total_offline_seconds"],
                "longest_offline_seconds": camera["longest_offline_seconds"],
                "current_offline_seconds": camera["current_offline_seconds"],
                "continuous_failure_active": camera["continuous_failure_active"],
            }
        )

    return {
        "generated_at": report["generated_at"],
        "hours": report["hours"],
        "criteria": report["criteria"],
        "overall": {
            "verdict": overall["verdict"],
            "monitored_cameras": overall["monitored_cameras"],
            "passed_cameras": overall["passed_cameras"],
            "failed_cameras": overall["failed_cameras"],
            "collecting_cameras": overall["collecting_cameras"],
            "online_rate": overall["recorder_availability_rate"],
            "recording_completeness": overall["recording_completeness"],
            "recording_gap_count": overall["recording_gap_count"],
            "missing_recording_seconds": overall["missing_recording_seconds"],
            "unexplained_recording_gaps": overall["unexplained_recording_gaps"],
            "ffmpeg_failures": overall["ffmpeg_failures"],
            "failure_streaks": overall["failure_streaks"],
            "outage_count": overall["outage_count"],
            "total_offline_seconds": overall["total_offline_seconds"],
            "longest_offline_seconds": overall["longest_offline_seconds"],
        },
        "cameras": cameras,
    }
