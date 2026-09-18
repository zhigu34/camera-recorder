from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.camera_discovery import OnvifDiscoveryResponse, RtspDiscoveryResponse


class CameraDiscoveryUnavailable(RuntimeError):
    pass


class CameraDiscoveryProtocolError(RuntimeError):
    pass


class CameraDiscoveryClient:
    def __init__(
        self,
        socket_path: str | Path | None = None,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.socket_path = Path(socket_path or settings.onvif_discovery_socket)
        self.timeout_seconds = max(0.01, float(timeout_seconds))

    async def _post(self, path: str, response_model):
        transport = httpx.AsyncHTTPTransport(uds=str(self.socket_path))
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://camera-discovery",
                    timeout=httpx.Timeout(self.timeout_seconds),
                ) as client:
                    response = await client.post(path, json={})
        except (TimeoutError, httpx.HTTPError, OSError) as exc:
            raise CameraDiscoveryUnavailable("camera discovery helper is unavailable") from exc

        if response.status_code >= 500:
            raise CameraDiscoveryUnavailable("camera discovery helper returned an error")
        if response.status_code != 200:
            raise CameraDiscoveryProtocolError(
                f"unexpected discovery helper status {response.status_code}"
            )

        try:
            payload = response.json()
            return response_model.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise CameraDiscoveryProtocolError("invalid discovery helper response") from exc

    async def scan_onvif(self) -> OnvifDiscoveryResponse:
        return await self._post("/scan/onvif", OnvifDiscoveryResponse)

    async def scan_rtsp(self) -> RtspDiscoveryResponse:
        return await self._post("/scan/rtsp", RtspDiscoveryResponse)


camera_discovery_client = CameraDiscoveryClient()
