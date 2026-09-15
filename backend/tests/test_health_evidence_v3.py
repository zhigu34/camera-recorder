import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

import app.main as main_module
from app.models.event import Event
from app.models.recording import Recording
from app.services.health_reliability import diagnose_recording_gaps


UTC = timezone.utc


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True


def _recording(recording_id: int, start: datetime, end: datetime) -> Recording:
    return Recording(
        id=recording_id,
        camera_id=1,
        started_at=start,
        ended_at=end,
        duration=(end - start).total_seconds(),
        mp4_path=f"/tmp/{recording_id}.mp4",
        status="ready",
        health_status="healthy",
        ffprobe_ok=1,
        has_video=1,
        upload_status="success",
        created_at=start,
        updated_at=end,
    )


def _event(
    *,
    code: str,
    created_at: datetime,
    metadata: dict | None = None,
    camera_id: int | None = 1,
) -> Event:
    return Event(
        camera_id=camera_id,
        level="info",
        category="recording" if code == "recording.deleted" else "system",
        code=code,
        message=code,
        metadata_json=json.dumps(metadata or {}),
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_backend_started_event_is_persisted_and_wired(monkeypatch) -> None:
    recorder = getattr(main_module, "_record_backend_started", None)
    assert recorder is not None

    session = FakeSession()
    monkeypatch.setattr(main_module, "SessionLocal", lambda: session)
    await recorder()

    events = [item for item in session.added if isinstance(item, Event)]
    assert len(events) == 1
    event = events[0]
    assert event.category == "system"
    assert event.code == "system.backend_started"
    assert event.camera_id is None
    assert session.committed is True
    assert "_record_backend_started()" in inspect.getsource(main_module.lifespan)


def test_manual_deletion_wins_gap_evidence_precedence() -> None:
    first_start = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    gap_start = first_start + timedelta(minutes=5)
    gap_end = first_start + timedelta(minutes=10)
    recordings = [
        _recording(1, first_start, gap_start),
        _recording(3, gap_end, gap_end + timedelta(minutes=5)),
    ]
    events = [
        _event(
            code="recording.segment_processing_failed",
            created_at=gap_start + timedelta(minutes=1),
            metadata={"segment_started_at": (gap_start + timedelta(minutes=1)).isoformat()},
        ),
        _event(
            code="recording.deleted",
            created_at=gap_start + timedelta(minutes=2),
            metadata={
                "recording_id": 2,
                "started_at": gap_start.isoformat(),
                "ended_at": gap_end.isoformat(),
                "reason": "manual",
            },
        ),
    ]

    gaps = diagnose_recording_gaps(
        recordings=recordings,
        samples=[],
        events=events,
        cutoff=first_start,
        now=gap_end + timedelta(minutes=5),
    )

    assert len(gaps) == 1
    assert gaps[0]["cause"] == "manual_deletion"
    assert gaps[0]["confidence"] == "high"


def test_backend_restart_is_bounded_gap_evidence() -> None:
    first_start = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    gap_start = first_start + timedelta(minutes=5)
    gap_end = first_start + timedelta(minutes=10)
    recordings = [
        _recording(1, first_start, gap_start),
        _recording(2, gap_end, gap_end + timedelta(minutes=5)),
    ]

    nearby = _event(
        code="system.backend_started",
        created_at=gap_start + timedelta(seconds=30),
        camera_id=None,
    )
    nearby_gaps = diagnose_recording_gaps(
        recordings=recordings,
        samples=[],
        events=[nearby],
        cutoff=first_start,
        now=gap_end + timedelta(minutes=5),
    )
    assert nearby_gaps[0]["cause"] == "backend_restart"
    assert nearby_gaps[0]["confidence"] == "medium"

    distant = _event(
        code="system.backend_started",
        created_at=first_start - timedelta(hours=2),
        camera_id=None,
    )
    distant_gaps = diagnose_recording_gaps(
        recordings=recordings,
        samples=[],
        events=[distant],
        cutoff=first_start,
        now=gap_end + timedelta(minutes=5),
    )
    assert distant_gaps[0]["cause"] == "unknown"
