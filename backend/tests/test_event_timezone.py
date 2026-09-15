from datetime import datetime

from app.core.timezone import configured_timezone_name
from app.schemas.event import EventRead


def test_configured_timezone_defaults_to_shanghai(monkeypatch) -> None:
    monkeypatch.delenv("TZ", raising=False)
    assert configured_timezone_name() == "Asia/Shanghai"


def test_configured_timezone_uses_valid_iana_name(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    assert configured_timezone_name() == "Asia/Shanghai"


def test_configured_timezone_invalid_falls_back_to_utc(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Invalid/Timezone")
    assert configured_timezone_name() == "UTC"


def test_event_timestamp_uses_configured_timezone(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Shanghai")

    event = EventRead(
        id=1,
        level="info",
        category="test",
        code="test.timezone",
        message="timezone test",
        created_at=datetime(2026, 9, 11, 8, 0, 0),
    )

    assert event.model_dump(mode="json")["created_at"] == "2026-09-11 16:00:00"


def test_event_timestamp_falls_back_to_utc_for_invalid_timezone(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Invalid/Timezone")

    event = EventRead(
        id=2,
        level="info",
        category="test",
        code="test.timezone.invalid",
        message="timezone fallback test",
        created_at=datetime(2026, 9, 11, 8, 0, 0),
    )

    assert event.model_dump(mode="json")["created_at"] == "2026-09-11 08:00:00"
