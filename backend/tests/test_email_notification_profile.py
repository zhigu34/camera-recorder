from fastapi.testclient import TestClient

from app.main import app
from app.services.notification_settings import (
    EmailNotificationConfig,
    EmailRecipientConfig,
    parse_email_recipients,
)


def test_named_recipients_and_nvr_mail_options_round_trip() -> None:
    with TestClient(app) as client:
        response = client.put(
            "/api/notifications/email",
            json={
                "email_enabled": True,
                "offline_alert_seconds": 60,
                "recovery_stable_seconds": 10,
                "notify_recovery": True,
                "smtp_sender_name": "NVR 通知",
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "smtp_auth_enabled": True,
                "smtp_username": "nvr@example.com",
                "smtp_password": "example-secret",
                "clear_smtp_password": False,
                "smtp_from": "nvr@example.com",
                "smtp_to": "ops@example.com,admin@example.com",
                "recipients": [
                    {"name": "运维", "address": "ops@example.com"},
                    {"name": "管理员", "address": "admin@example.com"},
                ],
                "smtp_use_ssl": True,
                "smtp_starttls": False,
                "smtp_timeout_seconds": 15,
                "email_attach_images": True,
                "email_capture_interval_seconds": 2,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["smtp_sender_name"] == "NVR 通知"
        assert body["smtp_auth_enabled"] is True
        assert body["email_attach_images"] is True
        assert body["email_capture_interval_seconds"] == 2
        assert body["recipients"] == [
            {"name": "运维", "address": "ops@example.com"},
            {"name": "管理员", "address": "admin@example.com"},
        ]
        assert body["smtp_to"] == "ops@example.com,admin@example.com"
        assert "smtp_password" not in body


def test_legacy_smtp_to_is_still_parsed_as_recipients() -> None:
    recipients = parse_email_recipients("[]", "ops@example.com, admin@example.com")
    assert [item.address for item in recipients] == ["ops@example.com", "admin@example.com"]


def test_server_auth_toggle_controls_required_credentials() -> None:
    without_auth = EmailNotificationConfig(
        smtp_host="smtp.example.com",
        smtp_from="nvr@example.com",
        smtp_to="ops@example.com",
        smtp_auth_enabled=False,
    )
    with_auth = EmailNotificationConfig(
        smtp_host="smtp.example.com",
        smtp_from="nvr@example.com",
        recipients=[EmailRecipientConfig(address="ops@example.com")],
        smtp_auth_enabled=True,
        smtp_username="nvr@example.com",
        smtp_password="secret",
    )
    missing_password = EmailNotificationConfig(
        smtp_host="smtp.example.com",
        smtp_from="nvr@example.com",
        smtp_to="ops@example.com",
        smtp_auth_enabled=True,
        smtp_username="nvr@example.com",
    )

    assert without_auth.configured is True
    assert with_auth.configured is True
    assert missing_password.configured is False
