import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services.onvif_client import OnvifNotification, OnvifSubscription
from app.services.onvif_event_manager import OnvifEventManager, OnvifEventRuntimeConfig


@pytest.mark.asyncio
async def test_manager_consumes_notification_and_unsubscribes() -> None:
    manager: OnvifEventManager
    seen: list[tuple[int, OnvifNotification]] = []
    unsubscribed: list[str] = []

    config = OnvifEventRuntimeConfig(
        camera_id=9,
        device_service_url="http://192.0.2.9/onvif/device_service",
        events_url="http://192.0.2.9/onvif/events",
        username="operator",
        password="secret",
        connection_revision=4,
    )
    notification = OnvifNotification(
        topic="tns1:RuleEngine/CellMotionDetector/Motion",
        occurred_at=datetime(2026, 9, 18, 7, 15, tzinfo=timezone.utc),
        event_type="motion",
        property_operation="Changed",
        source={"VideoSourceConfigurationToken": "video-1"},
        data={"IsMotion": "true"},
        active=True,
    )

    async def load(camera_id: int):
        assert camera_id == 9
        return config

    async def sink(camera_id: int, item: OnvifNotification) -> None:
        seen.append((camera_id, item))
        manager._running = False

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            assert kwargs["username"] == "operator"

        async def create_pullpoint_subscription(self, events_url: str):
            assert events_url == config.events_url
            return OnvifSubscription(
                reference_url="http://192.0.2.9/onvif/sub/1",
                current_time=datetime.now(timezone.utc),
                termination_time=datetime.now(timezone.utc) + timedelta(minutes=1),
            )

        async def pull_messages(self, subscription_url: str):
            assert subscription_url.endswith("/sub/1")
            return [notification]

        async def renew_subscription(self, subscription_url: str):
            raise AssertionError("renew should not be needed in this short test")

        async def unsubscribe(self, subscription_url: str) -> None:
            unsubscribed.append(subscription_url)

    manager = OnvifEventManager(
        config_loader=load,
        event_sink=sink,
        client_factory=FakeClient,
    )
    manager._running = True

    await manager._consume(config)

    assert seen == [(9, notification)]
    assert unsubscribed == ["http://192.0.2.9/onvif/sub/1"]
    assert manager.status(9)["last_event_at"] == notification.occurred_at


@pytest.mark.asyncio
async def test_stop_camera_cancels_task_without_restarting() -> None:
    manager = OnvifEventManager()
    manager._running = True
    started = asyncio.Event()

    async def sleeper() -> None:
        started.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(sleeper())
    manager._tasks[15] = task
    await started.wait()

    await manager.stop_camera(15)

    assert task.cancelled()
    assert manager.active_camera_ids() == []
    assert manager.status(15)["state"] == "disabled"
