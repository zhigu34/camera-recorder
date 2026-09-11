from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.notification_settings import NotificationSettings
from app.schemas.notification_settings import (
    EmailNotificationSettingsRead,
    EmailNotificationSettingsUpdate,
)
from app.services.email_notifier import email_notifier
from app.services.event_log import add_event
from app.services.notification_settings import (
    get_or_create_notification_settings,
    load_email_notification_config,
    update_smtp_password,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _serialize(row: NotificationSettings, configured: bool) -> EmailNotificationSettingsRead:
    return EmailNotificationSettingsRead(
        email_enabled=row.email_enabled,
        offline_alert_seconds=row.offline_alert_seconds,
        recovery_stable_seconds=row.recovery_stable_seconds,
        notify_recovery=row.notify_recovery,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_username=row.smtp_username,
        smtp_password_set=bool(row.smtp_password_encrypted),
        smtp_from=row.smtp_from,
        smtp_to=row.smtp_to,
        smtp_use_ssl=row.smtp_use_ssl,
        smtp_starttls=row.smtp_starttls,
        smtp_timeout_seconds=row.smtp_timeout_seconds,
        configured=configured,
    )


@router.get("/email", response_model=EmailNotificationSettingsRead)
async def email_settings(db: AsyncSession = Depends(get_db)):
    row = await get_or_create_notification_settings(db)
    await db.commit()
    config = await load_email_notification_config(db)
    return _serialize(row, config.configured)


@router.put("/email", response_model=EmailNotificationSettingsRead)
async def update_email_settings(
    payload: EmailNotificationSettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_notification_settings(db)

    row.email_enabled = payload.email_enabled
    row.offline_alert_seconds = payload.offline_alert_seconds
    row.recovery_stable_seconds = payload.recovery_stable_seconds
    row.notify_recovery = payload.notify_recovery
    row.smtp_host = payload.smtp_host.strip()
    row.smtp_port = payload.smtp_port
    row.smtp_username = payload.smtp_username.strip()
    row.smtp_from = payload.smtp_from.strip()
    row.smtp_to = payload.smtp_to.strip()
    row.smtp_use_ssl = payload.smtp_use_ssl
    row.smtp_starttls = payload.smtp_starttls
    row.smtp_timeout_seconds = payload.smtp_timeout_seconds
    update_smtp_password(row, payload.smtp_password, payload.clear_smtp_password)

    add_event(
        db,
        level="info",
        category="notification",
        code="notification.email_settings_updated",
        message="邮件告警配置已更新",
    )
    await db.commit()
    await db.refresh(row)
    config = await load_email_notification_config(db)
    return _serialize(row, config.configured)


@router.post("/email/test")
async def test_email(db: AsyncSession = Depends(get_db)) -> dict:
    config = await load_email_notification_config(db)
    if not config.configured:
        raise HTTPException(status_code=409, detail="SMTP 配置不完整")

    sent = await email_notifier.send_test()
    if not sent:
        raise HTTPException(status_code=502, detail="测试邮件发送失败，请查看事件中心")
    return {"sent": True}
