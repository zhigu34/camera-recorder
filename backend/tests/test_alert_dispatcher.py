import pytest

from app.services.alert_dispatcher import AlertDispatcher
from app.services.email_notifier import email_notifier
from app.services.notification_settings import EmailNotificationConfig


def _config(*, enabled: bool = True, recovery: bool = True) -> EmailNotificationConfig:
    return EmailNotificationConfig(
        email_enabled=enabled,
        notify_recovery=recovery,
        smtp_host="smtp.example.com",
        smtp_from="camera@example.com",
        smtp_to="ops@example.com",
    )


@pytest.mark.asyncio
async def test_alert_is_sent_once_until_cleared(monkeypatch):
    dispatcher = AlertDispatcher()
    sent: list[dict] = []

    async def fake_load_config():
        return _config()

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(email_notifier, "load_config", fake_load_config)
    monkeypatch.setattr(email_notifier, "send", fake_send)

    first = await dispatcher.alert(key="storage:critical", subject="critical", body="body")
    second = await dispatcher.alert(key="storage:critical", subject="critical", body="body")

    assert first is True
    assert second is False
    assert dispatcher.is_active("storage:critical") is True
    assert len(sent) == 1

    assert await dispatcher.clear("storage:critical") is True
    third = await dispatcher.alert(key="storage:critical", subject="critical", body="body")
    assert third is True
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_recovery_clears_incident_and_respects_recovery_switch(monkeypatch):
    dispatcher = AlertDispatcher()
    sent: list[str] = []
    current = _config(recovery=True)

    async def fake_load_config():
        return current

    async def fake_send(**kwargs):
        sent.append(kwargs["subject"])
        return True

    monkeypatch.setattr(email_notifier, "load_config", fake_load_config)
    monkeypatch.setattr(email_notifier, "send", fake_send)

    await dispatcher.alert(key="upload:failed", subject="failed", body="body")
    recovered = await dispatcher.recover(
        key="upload:failed",
        subject="recovered",
        body="body",
    )
    assert recovered is True
    assert sent == ["failed", "recovered"]
    assert dispatcher.is_active("upload:failed") is False

    current.notify_recovery = False
    await dispatcher.alert(key="upload:failed", subject="failed-again", body="body")
    recovered = await dispatcher.recover(
        key="upload:failed",
        subject="should-not-send",
        body="body",
    )
    assert recovered is False
    assert sent == ["failed", "recovered", "failed-again"]
    assert dispatcher.is_active("upload:failed") is False


@pytest.mark.asyncio
async def test_disabled_email_does_not_activate_incident(monkeypatch):
    dispatcher = AlertDispatcher()

    async def fake_load_config():
        return _config(enabled=False)

    async def fail_if_called(**kwargs):
        raise AssertionError("send should not be called")

    monkeypatch.setattr(email_notifier, "load_config", fake_load_config)
    monkeypatch.setattr(email_notifier, "send", fail_if_called)

    sent = await dispatcher.alert(key="camera:1:streak", subject="x", body="x")
    assert sent is False
    assert dispatcher.is_active("camera:1:streak") is False
