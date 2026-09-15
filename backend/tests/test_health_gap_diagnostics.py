import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import app.services.stability_report as stability_report
from app.core.config import settings
from app.services.segment_processor import SegmentProcessor


def _dt(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, 15, hour, minute, second, tzinfo=timezone.utc)


def _recording(start: datetime, end: datetime):
    return SimpleNamespace(started_at=start, ended_at=end, duration=(end - start).total_seconds())


def _sample(at: datetime, *, expected: bool = True, state: str = "RECORDING"):
    return SimpleNamespace(sampled_at=at, expected_recording=expected, state=state)


def _event(code: str, created_at: datetime, metadata: dict | None = None):
    return SimpleNamespace(
        code=code,
        created_at=created_at,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
    )


def test_gap_diagnostics_explain_segment_processing_failure() -> None:
    diagnose = getattr(stability_report, "diagnose_recording_gaps", None)
    assert callable(diagnose), "stability report must diagnose missing recording intervals"

    recordings = [
        _recording(_dt(10, 0), _dt(10, 5)),
        _recording(_dt(10, 10), _dt(10, 15)),
    ]
    samples = [_sample(_dt(10, minute)) for minute in range(5, 10)]
    events = [
        _event(
            "recording.segment_processing_failed",
            _dt(10, 6),
            {
                "segment_started_at": _dt(10, 5).isoformat(),
                "stage": "probe",
                "reason": "ffprobe failed",
            },
        )
    ]

    gaps = diagnose(
        recordings=recordings,
        samples=samples,
        events=events,
        cutoff=_dt(9, 0),
        now=_dt(11, 0),
    )

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["duration_seconds"] == 300
    assert gap["cause"] == "segment_processing_failed"
    assert gap["confidence"] == "high"
    assert "ffprobe failed" in gap["detail"]


def test_gap_diagnostics_explain_recorder_unavailable_and_never_leave_reason_blank() -> None:
    diagnose = getattr(stability_report, "diagnose_recording_gaps", None)
    assert callable(diagnose)

    recordings = [
        _recording(_dt(11, 0), _dt(11, 5)),
        _recording(_dt(11, 8), _dt(11, 12)),
        _recording(_dt(11, 16), _dt(11, 20)),
    ]
    samples = [
        _sample(_dt(11, 6), state="RECONNECTING"),
        _sample(_dt(11, 7), state="RECONNECTING"),
        _sample(_dt(11, 13)),
        _sample(_dt(11, 14)),
        _sample(_dt(11, 15)),
    ]

    gaps = diagnose(
        recordings=recordings,
        samples=samples,
        events=[],
        cutoff=_dt(10, 0),
        now=_dt(12, 0),
    )

    assert [gap["cause"] for gap in gaps] == ["recorder_unavailable", "unknown"]
    assert all(gap["detail"] for gap in gaps)
    assert gaps[0]["confidence"] == "medium"
    assert gaps[1]["confidence"] == "low"


def test_gap_diagnostics_ignore_planned_non_recording_interval() -> None:
    diagnose = getattr(stability_report, "diagnose_recording_gaps", None)
    assert callable(diagnose)

    gaps = diagnose(
        recordings=[
            _recording(_dt(12, 0), _dt(12, 5)),
            _recording(_dt(12, 10), _dt(12, 15)),
        ],
        samples=[_sample(_dt(12, minute), expected=False, state="STOPPED") for minute in range(5, 10)],
        events=[],
        cutoff=_dt(11, 0),
        now=_dt(13, 0),
    )

    assert gaps == []


def test_segment_processor_persists_failure_evidence_before_losing_source_context(tmp_path, monkeypatch) -> None:
    processor = SegmentProcessor()
    source = tmp_path / "2026-09-15_13-00-00.mkv"
    source.write_bytes(b"broken")
    failed_dir = tmp_path / "failed"
    monkeypatch.setattr(settings, "failed_dir", failed_dir)

    async def fail_processing(camera_id: int, path: Path) -> None:
        raise RuntimeError("ffprobe exploded")

    captured: dict[str, object] = {}

    async def record_failure(camera_id: int, original: Path, failed_path: Path, exc: Exception) -> None:
        captured.update(
            camera_id=camera_id,
            original=original,
            failed_path=failed_path,
            reason=str(exc),
        )

    processor.process_segment = fail_processing  # type: ignore[method-assign]
    processor._record_processing_failure = record_failure  # type: ignore[attr-defined]

    asyncio.run(processor._process_guarded(7, source, asyncio.Semaphore(1)))

    assert captured["camera_id"] == 7
    assert captured["original"] == source
    assert Path(captured["failed_path"]).exists()
    assert captured["reason"] == "ffprobe exploded"
