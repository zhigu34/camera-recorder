from fastapi.testclient import TestClient

from app.main import app


def test_email_notification_settings_do_not_expose_password() -> None:
    with TestClient(app) as client:
        response = client.put(
            "/api/notifications/email",
            json={
                "email_enabled": True,
                "offline_alert_seconds": 60,
                "recovery_stable_seconds": 10,
                "notify_recovery": True,
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "camera@example.com",
                "smtp_password": "example-secret",
                "clear_smtp_password": False,
                "smtp_from": "camera@example.com",
                "smtp_to": "ops@example.com",
                "smtp_use_ssl": False,
                "smtp_starttls": True,
                "smtp_timeout_seconds": 15,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["smtp_password_set"] is True
        assert "smtp_password" not in body

        response = client.get("/api/notifications/email")
        assert response.status_code == 200
        body = response.json()
        assert body["smtp_password_set"] is True
        assert "smtp_password" not in body

        response = client.put(
            "/api/notifications/email",
            json={
                "email_enabled": True,
                "offline_alert_seconds": 90,
                "recovery_stable_seconds": 15,
                "notify_recovery": True,
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "camera@example.com",
                "smtp_password": None,
                "clear_smtp_password": False,
                "smtp_from": "camera@example.com",
                "smtp_to": "ops@example.com",
                "smtp_use_ssl": False,
                "smtp_starttls": True,
                "smtp_timeout_seconds": 15,
            },
        )
        assert response.status_code == 200
        assert response.json()["smtp_password_set"] is True


def test_email_notification_rejects_ssl_and_starttls_together() -> None:
    with TestClient(app) as client:
        response = client.put(
            "/api/notifications/email",
            json={
                "email_enabled": False,
                "offline_alert_seconds": 60,
                "recovery_stable_seconds": 10,
                "notify_recovery": True,
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "smtp_username": "",
                "smtp_password": None,
                "clear_smtp_password": False,
                "smtp_from": "camera@example.com",
                "smtp_to": "ops@example.com",
                "smtp_use_ssl": True,
                "smtp_starttls": True,
                "smtp_timeout_seconds": 15,
            },
        )
        assert response.status_code == 422
