from datetime import timedelta

from app.services.motion_worker import deployment_now


def test_motion_timestamp_uses_deployment_timezone(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    value = deployment_now()
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(hours=8)
