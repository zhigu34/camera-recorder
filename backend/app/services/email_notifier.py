import asyncio
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage

from app.core.database import SessionLocal
from app.services.event_log import add_event
from app.services.notification_settings import EmailNotificationConfig, load_email_notification_config


class EmailNotifier:
    async def load_config(self) -> EmailNotificationConfig:
        async with SessionLocal() as session:
            return await load_email_notification_config(session)

    async def send(
        self,
        *,
        subject: str,
        body: str,
        camera_id: int | None = None,
        success_code: str = "notification.email_sent",
        config: EmailNotificationConfig | None = None,
    ) -> bool:
        config = config or await self.load_config()
        if not config.configured:
            return False

        try:
            await asyncio.to_thread(self._send_sync, config, subject, body)
        except Exception as exc:
            await self._record_event(
                level="error",
                code="notification.email_failed",
                message=f"邮件通知发送失败: {str(exc)[-500:]}",
                camera_id=camera_id,
            )
            return False

        await self._record_event(
            level="info",
            code=success_code,
            message=f"邮件通知已发送: {subject}",
            camera_id=camera_id,
        )
        return True

    async def send_offline(
        self,
        *,
        camera_id: int,
        camera_name: str,
        camera_ip: str,
        rtsp_path: str,
        offline_since: datetime,
        last_error: str | None,
        restart_count: int,
        config: EmailNotificationConfig | None = None,
    ) -> bool:
        config = config or await self.load_config()
        now = datetime.now(timezone.utc)
        offline_seconds = max(0, int((now - offline_since).total_seconds()))
        subject = f"[Camera Recorder] 摄像头掉线：{camera_name}"
        body = (
            f"检测到摄像头持续掉线。\n\n"
            f"摄像头：{camera_name}\n"
            f"IP：{camera_ip}\n"
            f"RTSP Path：{rtsp_path}\n"
            f"掉线开始：{offline_since.astimezone().isoformat(timespec='seconds')}\n"
            f"持续时间：约 {offline_seconds} 秒\n"
            f"自动重连次数：{restart_count}\n"
            f"最近错误：{last_error or '-'}\n\n"
            f"系统仍会继续自动重连；本通知在本次掉线期间只发送一次。\n"
        )
        return await self.send(
            subject=subject,
            body=body,
            camera_id=camera_id,
            success_code="notification.camera_offline_email_sent",
            config=config,
        )

    async def send_recovery(
        self,
        *,
        camera_id: int,
        camera_name: str,
        camera_ip: str,
        rtsp_path: str,
        offline_since: datetime,
        config: EmailNotificationConfig | None = None,
    ) -> bool:
        config = config or await self.load_config()
        if not config.notify_recovery:
            return False

        now = datetime.now(timezone.utc)
        offline_seconds = max(0, int((now - offline_since).total_seconds()))
        subject = f"[Camera Recorder] 摄像头已恢复：{camera_name}"
        body = (
            f"摄像头录像连接已经稳定恢复。\n\n"
            f"摄像头：{camera_name}\n"
            f"IP：{camera_ip}\n"
            f"RTSP Path：{rtsp_path}\n"
            f"本次不可用时长：约 {offline_seconds} 秒\n"
            f"恢复时间：{now.astimezone().isoformat(timespec='seconds')}\n"
        )
        return await self.send(
            subject=subject,
            body=body,
            camera_id=camera_id,
            success_code="notification.camera_recovery_email_sent",
            config=config,
        )

    async def send_test(self) -> bool:
        config = await self.load_config()
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        return await self.send(
            subject="[Camera Recorder] 邮件通知测试",
            body=f"这是一封 Camera Recorder 测试邮件。\n\n发送时间：{now}\n",
            success_code="notification.test_email_sent",
            config=config,
        )

    @staticmethod
    def _send_sync(config: EmailNotificationConfig, subject: str, body: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = config.smtp_from
        message["To"] = ", ".join(config.recipients)
        message.set_content(body)

        if config.smtp_use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=config.smtp_timeout_seconds,
                context=context,
            ) as smtp:
                EmailNotifier._login(smtp, config)
                smtp.send_message(message)
            return

        with smtplib.SMTP(
            config.smtp_host,
            config.smtp_port,
            timeout=config.smtp_timeout_seconds,
        ) as smtp:
            smtp.ehlo()
            if config.smtp_starttls:
                context = ssl.create_default_context()
                smtp.starttls(context=context)
                smtp.ehlo()
            EmailNotifier._login(smtp, config)
            smtp.send_message(message)

    @staticmethod
    def _login(smtp: smtplib.SMTP, config: EmailNotificationConfig) -> None:
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)

    @staticmethod
    async def _record_event(
        *,
        level: str,
        code: str,
        message: str,
        camera_id: int | None,
    ) -> None:
        try:
            async with SessionLocal() as session:
                add_event(
                    session,
                    level=level,
                    category="notification",
                    code=code,
                    message=message,
                    camera_id=camera_id,
                )
                await session.commit()
        except Exception:
            pass


email_notifier = EmailNotifier()
