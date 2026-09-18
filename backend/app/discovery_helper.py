from __future__ import annotations

import asyncio

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.schemas.camera_discovery import OnvifDiscoveryResponse, RtspDiscoveryResponse
from app.services.camera_discovery import scan_onvif, scan_rtsp_port_554


class DiscoveryScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


app = FastAPI(title="Camera Recorder LAN Discovery", version="1")


async def _scan_onvif() -> OnvifDiscoveryResponse:
    return await asyncio.to_thread(scan_onvif, 3.0)


async def _scan_rtsp() -> RtspDiscoveryResponse:
    return await scan_rtsp_port_554()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/scan/onvif", response_model=OnvifDiscoveryResponse)
async def scan_onvif_devices(_payload: DiscoveryScanRequest) -> OnvifDiscoveryResponse:
    return await _scan_onvif()


@app.post("/scan/rtsp", response_model=RtspDiscoveryResponse)
async def scan_rtsp_devices(_payload: DiscoveryScanRequest) -> RtspDiscoveryResponse:
    return await _scan_rtsp()
