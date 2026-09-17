from __future__ import annotations

from pydantic import BaseModel

from app.services.hik_bridge_client import HikBridgeClient, HikBridgeClientError


class CameraAdapterCapability(BaseModel):
    id: str
    label: str
    available: bool
    unavailable_reason: str | None = None


async def list_camera_adapter_capabilities() -> list[CameraAdapterCapability]:
    capabilities = [
        CameraAdapterCapability(id="manual_rtsp", label="Manual RTSP", available=True),
        CameraAdapterCapability(id="onvif", label="ONVIF", available=True),
    ]

    try:
        await HikBridgeClient().health()
    except HikBridgeClientError as exc:
        capabilities.append(
            CameraAdapterCapability(
                id="hik_sdk",
                label="Hikvision SDK",
                available=False,
                unavailable_reason=str(exc),
            )
        )
    else:
        capabilities.append(
            CameraAdapterCapability(id="hik_sdk", label="Hikvision SDK", available=True)
        )
    return capabilities
