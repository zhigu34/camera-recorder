from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret, encrypt_secret
from app.models.notification_settings import NotificationSettings


@dataclass(slots=True)
class EmailNotificationConfig:
    email_enabled: bool = False
    offline_alert_seconds: float = 60.0
    recovery_stable_seconds: float = 10.0
    notify_recovery: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_use_ssl: bool = False
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = 15.0

    @property
    def recipients(self) -> list[str]:
        return [item.strip() for item in self.smtp_to.split(",") if item.strip()]

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host.strip() and self.smtp_from.strip() and self.recipients)

    @property
    def configured(self) -> bool:
        return self.smtp_configured


async def get_or_create_notification_settings(session: AsyncSession) -> NotificationSettings:
    row = await session.get(NotificationSettings, 1)
    if row is not None:
        return row

    row = NotificationSettings(id=1)
    session.add(row)
    await session.flush()
    return row


async def load_email_notification_config(session: AsyncSession) -> EmailNotificationConfig:
    row = await session.get(NotificationSettings, 1)
    if row is None:
        return EmailNotificationConfig()

    password = ""
    if row.smtp_password_encrypted:
        try:
            password = decrypt_secret(row.smtp_password_encrypted)
        except Exception:
            password = ""

    return EmailNotificationConfig(
        email_enabled=row.email_enabled,
        offline_alert_seconds=row.offline_alert_seconds,
        recovery_stable_seconds=row.recovery_stable_seconds,
        notify_recovery=row.notify_recovery,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_username=row.smtp_username,
        smtp_password=password,
        smtp_from=row.smtp_from,
        smtp_to=row.smtp_to,
        smtp_use_ssl=row.smtp_use_ssl,
        smtp_starttls=row.smtp_starttls,
        smtp_timeout_seconds=row.smtp_timeout_seconds,
    )


def update_smtp_password(row: NotificationSettings, password: str | None, clear: bool) -> None:
    if clear:
        row.smtp_password_encrypted = None
    elif password:
        row.smtp_password_encrypted = encrypt_secret(password)
