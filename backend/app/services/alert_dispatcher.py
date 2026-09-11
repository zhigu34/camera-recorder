import asyncio
from typing import Any

from app.services.email_notifier import email_notifier


class AlertDispatcher:
    """Deduplicate email alerts for the lifetime of one active incident.

    Callers use a stable incident key. An alert is sent at most once until the
    incident is cleared/recovered. SMTP configuration and the existing global
    email_enabled switch remain the single source of truth.
    """

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._lock = asyncio.Lock()

    def is_active(self, key: str) -> bool:
        return key in self._active

    async def alert(
        self,
        *,
        key: str,
        subject: str,
        body: str,
        camera_id: int | None = None,
        success_code: str = "notification.system_alert_email_sent",
    ) -> bool:
        config = await email_notifier.load_config()
        if not config.email_enabled or not config.configured:
            return False

        async with self._lock:
            if key in self._active:
                return False
            self._active.add(key)

        return await email_notifier.send(
            subject=subject,
            body=body,
            camera_id=camera_id,
            success_code=success_code,
            config=config,
        )

    async def clear(self, key: str) -> bool:
        async with self._lock:
            existed = key in self._active
            self._active.discard(key)
            return existed

    async def recover(
        self,
        *,
        key: str,
        subject: str,
        body: str,
        camera_id: int | None = None,
        success_code: str = "notification.system_recovery_email_sent",
    ) -> bool:
        async with self._lock:
            if key not in self._active:
                return False
            self._active.discard(key)

        config = await email_notifier.load_config()
        if not config.email_enabled or not config.notify_recovery or not config.configured:
            return False

        return await email_notifier.send(
            subject=subject,
            body=body,
            camera_id=camera_id,
            success_code=success_code,
            config=config,
        )

    def snapshot(self) -> dict[str, Any]:
        return {"active_incidents": sorted(self._active), "active_count": len(self._active)}


alert_dispatcher = AlertDispatcher()
