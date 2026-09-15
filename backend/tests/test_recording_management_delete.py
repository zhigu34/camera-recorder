import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.api.recording_management as recording_management_api
from app.models.event import Event
from app.models.recording import Recording


class FakeSession:
    def __init__(self, recordings: list[Recording]) -> None:
        self.recordings = {recording.id: recording for recording in recordings}
        self.deleted: list[Recording] = []
        self.added: list[object] = []
        self.committed = False
        self.executed = 0

    async def get(self, model, recording_id: int):
        return self.recordings.get(recording_id)

    async def execute(self, statement):
        self.executed += 1
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def delete(self, recording: Recording):
        self.deleted.append(recording)
        self.recordings.pop(recording.id, None)

    async def commit(self):
        self.committed = True


def make_recording(path: Path, *, recording_id: int = 1, upload_status: str = "pending") -> Recording:
    started_at = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)
    return Recording(
        id=recording_id,
        camera_id=1,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=5),
        duration=300,
        mp4_path=str(path),
        status="ready",
        health_status="healthy",
        warning_count=0,
        timestamp_warning_count=0,
        network_warning_count=0,
        upload_status=upload_status,
    )


@pytest.fixture(autouse=True)
def disable_playback_cache_cleanup(monkeypatch):
    async def noop(recording_id: int) -> None:
        return None

    monkeypatch.setattr(recording_management_api, "_purge_playback_cache", noop)


@pytest.mark.asyncio
async def test_archived_delete_removes_local_file_but_keeps_remote_record(tmp_path: Path):
    path = tmp_path / "archived.mp4"
    path.write_bytes(b"video")
    recording = make_recording(path, upload_status="success")
    session = FakeSession([recording])

    result = await recording_management_api._delete_recordings([recording.id], session)

    assert not path.exists()
    assert recording.status == "deleted"
    assert session.deleted == []
    assert result.deleted_local == 1
    assert result.archived_remote_only == 1
    assert result.removed_records == 0
    assert session.committed is True


@pytest.mark.asyncio
async def test_unarchived_delete_removes_local_file_and_database_record(tmp_path: Path):
    path = tmp_path / "pending.mp4"
    path.write_bytes(b"video")
    recording = make_recording(path, upload_status="pending")
    session = FakeSession([recording])

    result = await recording_management_api._delete_recordings([recording.id], session)

    assert not path.exists()
    assert session.deleted == [recording]
    assert session.executed == 1
    assert result.deleted_local == 1
    assert result.archived_remote_only == 0
    assert result.removed_records == 1
    assert session.committed is True

    evidence = [item for item in session.added if isinstance(item, Event)]
    assert len(evidence) == 1
    event = evidence[0]
    assert event.category == "recording"
    assert event.code == "recording.deleted"
    assert event.camera_id == 1
    metadata = json.loads(event.metadata_json or "{}")
    assert metadata["recording_id"] == recording.id
    assert metadata["started_at"] == recording.started_at.isoformat()
    assert metadata["ended_at"] == recording.ended_at.isoformat()
    assert metadata["local_available_before"] is True
    assert metadata["cloud_available"] is False
    assert metadata["reason"] == "manual"


@pytest.mark.asyncio
async def test_uploading_recording_is_skipped_without_touching_file(tmp_path: Path):
    path = tmp_path / "uploading.mp4"
    path.write_bytes(b"video")
    recording = make_recording(path, upload_status="uploading")
    session = FakeSession([recording])

    result = await recording_management_api._delete_recordings([recording.id], session)

    assert path.exists()
    assert session.deleted == []
    assert not [item for item in session.added if isinstance(item, Event)]
    assert result.deleted_local == 0
    assert result.skipped_uploading == [recording.id]
    assert session.committed is True
