from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.camera_discovery import OnvifDiscoveryResponse, RtspDiscoveryResponse
from app.services.camera_discovery_client import (
    CameraDiscoveryClient,
    CameraDiscoveryProtocolError,
    CameraDiscoveryUnavailable,
)


router = APIRouter(prefix="/api/camera-discovery", tags=["camera-discovery"])
discovery_client = CameraDiscoveryClient()


@router.post("/onvif", response_model=OnvifDiscoveryResponse)
async def discover_onvif_devices() -> OnvifDiscoveryResponse:
    try:
        return await discovery_client.scan_onvif()
    except CameraDiscoveryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="ONVIF 局域网发现当前不可用",
        ) from exc
    except CameraDiscoveryProtocolError as exc:
        raise HTTPException(
            status_code=502,
            detail="ONVIF 局域网发现返回了无效响应",
        ) from exc


@router.post("/rtsp", response_model=RtspDiscoveryResponse)
async def discover_rtsp_devices() -> RtspDiscoveryResponse:
    try:
        return await discovery_client.scan_rtsp()
    except CameraDiscoveryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="RTSP 局域网发现当前不可用",
        ) from exc
    except CameraDiscoveryProtocolError as exc:
        raise HTTPException(
            status_code=502,
            detail="RTSP 局域网发现返回了无效响应",
        ) from exc
