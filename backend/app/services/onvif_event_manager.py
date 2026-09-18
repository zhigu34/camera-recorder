from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.models.camera import Camera
from app.models.detection_event import DetectionEvent
from app.models.onvif_events import OnvifEventSettings
from app.services.onvif_client import OnvifClient, OnvifNotification

EnabledCameraLoader = Callable[[], Awaitable[list[int]]]
ConfigLoader = Callable[[int], Awaitable["OnvifEventRuntimeConfig | None"]]
EventSink = Callable[[int, OnvifNotification], Awaitable[None]]
ClientFactory = Callable[..., OnvifClient]


@dataclass(frozen=True)
class OnvifEventRuntimeConfig:
    camera_id: int
    device_service_url: str
    events_url: str
    username: str
    password: str
    connection_revision: int


async def _default_enabled_camera_loader() -> list[int]:
    async with SessionLocal() as db:
        result = await db.scalars(
            select(OnvifEventSettings.camera_id)
            .where(OnvifEventSettings.enabled.is_(True))
            .order_by(OnvifEventSettings.camera_id)
        )
        return list(result)


async def _default_config_loader(camera_id: int) -> OnvifEventRuntimeConfig | None:
    async with SessionLocal() as db:
        camera = await db.get(Camera, camera_id)
        settings = await db.get(OnvifEventSettings, camera_id)
        if camera is None or settings is None or not settings.enabled or not camera.enabled:
            return None

        connection = camera.connection
        if (
            connection is None
            or connection.adapter != "onvif"
            or connection.verification_status != "verified"
            or connection.onvif_config is None
        ):
            return None

        capabilities = connection.onvif_config.capabilities_json or {}
        events_url = capabilities.get("events_xaddr")
        if not isinstance(events_url, str) or not events_url:
            return None

        try:
            password = decrypt_secret(connection.password_encrypted)
        except Exception:
            return None

        return OnvifEventRuntimeConfig(
            camera_id=camera_id,
            device_service_url=connection.onvif_config.device_service_url,
            events_url=events_url,
            username=connection.username,
            password=password,
            connection_revision=int(connection.revision),
        )


async def _default_event_sink(camera_id: int, notification: OnvifNotification) -> None:
    if notification.active is False:
        return

    metadata: dict[str, Any] = {
        "source_id": "camera.onvif",
        "topic": notification.topic,
        "source": notification.source,
        "data": notification.data,
        "property_operation": notification.property_operation,
        "active": notification.active,
    }
    async with SessionLocal() as db:
        db.add(
            DetectionEvent(
                camera_id=camera_id,
                source_kind="camera_native",
                provider="onvif",
                event_type=notification.event_type,
                started_at=notification.occurred_at,
                ended_at=notification.occurred_at,
                metadata_json=metadata,
            )
        )
        await db.commit()


class OnvifEventManager:
    def __init__(
        self,
        *,
        enabled_camera_loader: EnabledCameraLoader = _default_enabled_camera_loader,
        config_loader: ConfigLoader = _default_config_loader,
        event_sink: EventSink = _default_event_sink,
        client_factory: ClientFactory = OnvifClient,
        reconnect_delays: tuple[float, ...] = (2.0, 5.0, 10.0, 30.0),
    ) -> None:
        self.enabled_camera_loader = enabled_camera_loader
        self.config_loader = config_loader
        self.event_sink = event_sink
        self.client_factory = client_factory
        self.reconnect_delays = reconnect_delays or (2.0,)
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._status: dict[int, dict[str, Any]] = {}
        self._running = False

    @staticmethod
    def _default_status() -> dict[str, Any]:
        return {
            "state": "disabled",
            "last_event_at": None,
            "last_error": None,
            "subscription_url": None,
            "reconnect_count": 0,
        }

    def status(self, camera_id: int) -> dict[str, Any]:
        return dict(self._status.get(camera_id, self._default_status()))

    def active_camera_ids(self) -> list[int]:
        return sorted(camera_id for camera_id, task in self._tasks.items() if not task.done())

    def _set_status(self, camera_id: int, state: str, **changes: Any) -> None:
        value = {**self._default_status(), **self._status.get(camera_id, {}), **changes}
        value["state"] = state
        self._status[camera_id] = value

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for camera_id in await self.enabled_camera_loader():
            self._start_camera(camera_id)

    async def stop(self) -> None:
        self._running = False
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for camera_id in list(self._status):
            self._set_status(camera_id, "stopped", subscription_url=None)

    async def stop_camera(self, camera_id: int) -> None:
        task = self._tasks.pop(camera_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._set_status(camera_id, "disabled", subscription_url=None, last_error=None)

    async def restart_camera(self, camera_id: int) -> None:
        await self.stop_camera(camera_id)

        if not self._running:
            return
        if await self.config_loader(camera_id) is None:
            self._set_status(camera_id, "disabled", subscription_url=None, last_error=None)
            return
        self._start_camera(camera_id)

    def _start_camera(self, camera_id: int) -> None:
        task = self._tasks.get(camera_id)
        if task is not None and not task.done():
            return
        self._tasks[camera_id] = asyncio.create_task(
            self._run_camera(camera_id),
            name=f"onvif-events-{camera_id}",
        )

    async def _run_camera(self, camera_id: int) -> None:
        attempt = 0
        while self._running:
            config = await self.config_loader(camera_id)
            if config is None:
                self._set_status(camera_id, "disabled", subscription_url=None, last_error=None)
                return
            try:
                self._set_status(camera_id, "starting", last_error=None)
                await self._consume(config)
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                self._set_status(
                    camera_id,
                    "reconnecting",
                    last_error=str(exc),
                    subscription_url=None,
                    reconnect_count=attempt,
                )
                delay = self.reconnect_delays[min(attempt - 1, len(self.reconnect_delays) - 1)]
                await asyncio.sleep(delay)

    async def _consume(self, config: OnvifEventRuntimeConfig) -> None:
        client = self.client_factory(
            device_service_url=config.device_service_url,
            username=config.username,
            password=config.password,
        )
        subscription = await client.create_pullpoint_subscription(config.events_url)
        termination = subscription.termination_time
        self._set_status(
            config.camera_id,
            "running",
            last_error=None,
            subscription_url=subscription.reference_url,
        )

        try:
            while self._running:
                latest = await self.config_loader(config.camera_id)
                if latest is None:
                    return
                if latest.connection_revision != config.connection_revision:
                    return

                notifications = await client.pull_messages(subscription.reference_url)
                for notification in notifications:
                    await self.event_sink(config.camera_id, notification)
                    self._set_status(
                        config.camera_id,
                        "running",
                        last_event_at=notification.occurred_at,
                        last_error=None,
                    )

                now = datetime.now(timezone.utc)
                if termination is None or termination <= now + timedelta(seconds=20):
                    termination = await client.renew_subscription(subscription.reference_url)
        finally:
            try:
                await client.unsubscribe(subscription.reference_url)
            except Exception:
                pass
            self._set_status(config.camera_id, "reconnecting", subscription_url=None)


onvif_event_manager = OnvifEventManager()
