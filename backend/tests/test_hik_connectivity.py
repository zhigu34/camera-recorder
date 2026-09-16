import pytest

from app.services.hik_bridge_client import HikBridgeClientError
from app.services.camera_connectivity_monitor import (
    probe_hik_service,
    resolve_connectivity_observation,
)


class FakeBridgeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    async def probe(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise HikBridgeClientError("offline")
        return {"serial_number": "DS-TEST"}


@pytest.mark.asyncio
async def test_hik_connectivity_uses_sdk_login_probe() -> None:
    client = FakeBridgeClient()

    assert await probe_hik_service(
        "10.0.0.8",
        8000,
        "admin",
        "secret",
        bridge_client=client,
    ) is True
    assert client.calls == [{
        "host": "10.0.0.8",
        "port": 8000,
        "username": "admin",
        "password": "secret",
    }]


@pytest.mark.asyncio
async def test_hik_connectivity_failure_is_a_normal_negative_observation() -> None:
    assert await probe_hik_service(
        "10.0.0.8",
        8000,
        "admin",
        "secret",
        bridge_client=FakeBridgeClient(fail=True),
    ) is False


def test_hik_observation_reports_hik_sdk_as_probe_source() -> None:
    result = resolve_connectivity_observation(
        previous_status="offline",
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=True,
        previous_failures=3,
        probe_source="hik_sdk",
    )
    assert result.status == "online"
    assert result.consecutive_failures == 0
    assert result.source == "hik_sdk"
