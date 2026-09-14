from datetime import datetime

import pytest

from app.api import events as events_api
from app.models.event import Event
from app.models.motion import MotionEvent


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, motion_event: MotionEvent):
        self.motion_event = motion_event

    async def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is MotionEvent:
            return _Rows([self.motion_event])
        if entity is Event:
            return _Rows([])
        return _Rows([])


class _SessionContext:
    def __init__(self, motion_event: MotionEvent):
        self.session = _Session(motion_event)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _WebSocket:
    def __init__(self):
        self.query_params = {"after_id": "0", "after_motion_id": "6"}
        self.sent: list[dict] = []

    async def accept(self):
        return None

    async def send_json(self, payload: dict):
        self.sent.append(payload)

    async def receive(self):
        return {"type": "websocket.disconnect"}


@pytest.mark.asyncio
async def test_events_websocket_streams_new_motion_events(monkeypatch) -> None:
    motion_event = MotionEvent(
        id=7,
        camera_id=3,
        zone_id=None,
        recording_id=11,
        started_at=datetime(2026, 9, 14, 20, 30, 0),
        ended_at=datetime(2026, 9, 14, 20, 30, 4),
        peak_score=0.84,
        snapshot_path="motion/test.jpg",
        metadata_json='{"detector":"motion-v2"}',
        created_at=datetime(2026, 9, 14, 20, 30, 5),
    )
    websocket = _WebSocket()
    monkeypatch.setattr(events_api, "SessionLocal", lambda: _SessionContext(motion_event))

    await events_api.events_websocket(websocket)

    assert websocket.sent == [
        {
            "type": "motion.created",
            "data": {
                "id": 7,
                "camera_id": 3,
                "zone_id": None,
                "recording_id": 11,
                "started_at": "2026-09-14T20:30:00",
                "ended_at": "2026-09-14T20:30:04",
                "peak_score": 0.84,
                "snapshot_path": "motion/test.jpg",
                "metadata_json": '{"detector":"motion-v2"}',
                "created_at": "2026-09-14T20:30:05",
            },
        }
    ]
