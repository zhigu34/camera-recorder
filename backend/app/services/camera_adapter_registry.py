from __future__ import annotations

from pydantic import BaseModel

from app.core.config import settings
from app.services.hik_bridge_client import HikBridgeClient, HikBridgeClientError

HIK_DISABLED_REASON = "HIK SDK adapter is disabled by deployment configuration"
HIK_RUNTIME_UNAVAILABLE_REASON = "HIK SDK runtime is unavailable"


class CameraAdapterCapability(BaseModel):
    id: str
    label: str
    available: bool
    unavailable_reason: str | None = None


async def get_camera_adapter_capability(adapter: str) -> CameraAdapterCapability:
    if adapter == "manual_rtsp":
        return CameraAdapterCapability(id="manual_rtsp", label="Manual RTSP", available=True)
    if adapter == "onvif":
        return CameraAdapterCapability(id="onvif", label="ONVIF", available=True)
    if adapter != "hik_sdk":
        raise ValueError(f"unsupported camera adapter: {adapter}")

    if not settings.hik_enabled:
        return CameraAdapterCapability(
            id="hik_sdk",
            label="Hikvision SDK",
            available=False,
            unavailable_reason=HIK_DISABLED_REASON,
        )

    try:
        health = await HikBridgeClient().health()
    except HikBridgeClientError as exc:
        return CameraAdapterCapability(
            id="hik_sdk",
            label="Hikvision SDK",
            available=False,
            unavailable_reason=str(exc),
        )

    if health.get("runtime_available") is not True:
        return CameraAdapterCapability(
            id="hik_sdk",
            label="Hikvision SDK",
            available=False,
            unavailable_reason=HIK_RUNTIME_UNAVAILABLE_REASON,
        )

    return CameraAdapterCapability(id="hik_sdk", label="Hikvision SDK", available=True)


async def list_camera_adapter_capabilities() -> list[CameraAdapterCapability]:
    return [
        await get_camera_adapter_capability("manual_rtsp"),
        await get_camera_adapter_capability("onvif"),
        await get_camera_adapter_capability("hik_sdk"),
    ]
