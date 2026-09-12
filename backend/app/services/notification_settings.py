import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret, encrypt_secret
from app.models.notification_settings import NotificationSettings


@dataclass(slots=True)
class EmailRecipientConfig:
    name: str = ""
    address: str = ""


@dataclass(slots=True)
class EmailNotificationConfig:
    email_enabled: bool = False
    offline_alert_seconds: float = 60.0
    recovery_stable_seconds: float = 10.0
    notify_recovery: bool = True
    smtp_sender_name: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_auth_enabled: bool = True
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    recipients: list[EmailRecipientConfig] | None = None
    smtp_use_ssl: bool = False
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = 15.0
    email_attach_images: bool = False
    email_capture_interval_seconds: int = 2

    @property
    def recipient_entries(self) -> list[EmailRecipientConfig]:
        if self.recipients:
            return [item for item in self.recipients if item.address.strip()]
        return [
            EmailRecipientConfig(address=item.strip())
            for item in self.smtp_to.split(",")
            if item.strip()
        ]

    @property
    def recipient_addresses(self) -> list[str]:
        return [item.address.strip() for item in self.recipient_entries]

    @property
    def smtp_configured(self) -> bool:
        base = bool(self.smtp_host.strip() and self.smtp_from.strip() and self.recipient_addresses)
        if not base:
            return False
        if self.smtp_auth_enabled:
            return bool(self.smtp_username.strip() and self.smtp_password)
        return True

    @property
    def configured(self) -> bool:
        return self.smtp_configured


def parse_email_recipients(raw: str | None, fallback: str = "") -> list[EmailRecipientConfig]:
    if raw:
        try:
            data = json.loads(raw)
            result = []
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    address = str(item.get("address") or "").strip()
                    if not address:
                        continue
                    result.append(
                        EmailRecipientConfig(
                            name=str(item.get("name") or "").strip(),
                            address=address,
                        )
                    )
            if result:
                return result
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return [
        EmailRecipientConfig(address=item.strip())
        for item in fallback.split(",")
        if item.strip()
    ]


def serialize_email_recipients(recipients: list[object]) -> str:
    payload: list[dict[str, str]] = []
    for item in recipients:
        name = str(getattr(item, "name", "") or "").strip()
        address = str(getattr(item, "address", "") or "").strip()
        if address:
            payload.append({"name": name, "address": address})
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


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
        smtp_sender_name=row.smtp_sender_name,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_auth_enabled=row.smtp_auth_enabled,
        smtp_username=row.smtp_username,
        smtp_password=password,
        smtp_from=row.smtp_from,
        smtp_to=row.smtp_to,
        recipients=parse_email_recipients(row.smtp_recipients_json, row.smtp_to),
        smtp_use_ssl=row.smtp_use_ssl,
        smtp_starttls=row.smtp_starttls,
        smtp_timeout_seconds=row.smtp_timeout_seconds,
        email_attach_images=row.email_attach_images,
        email_capture_interval_seconds=row.email_capture_interval_seconds,
    )


def update_smtp_password(row: NotificationSettings, password: str | None, clear: bool) -> None:
    if clear:
        row.smtp_password_encrypted = None
    elif password:
        row.smtp_password_encrypted = encrypt_secret(password)
