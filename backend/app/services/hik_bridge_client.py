from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.services.hik_media_adapter import HikBridgeTarget


class HikBridgeClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class HikBridgeClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.hik_bridge_url).rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        secrets: tuple[str, ...] = (),
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise HikBridgeClientError("HIK bridge request failed") from exc

        if response.status_code >= 400:
            detail = "HIK bridge request failed"
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("detail"):
                    detail = str(body["detail"])
            except (ValueError, TypeError):
                pass
            for secret in secrets:
                if secret:
                    detail = detail.replace(secret, "***")
            raise HikBridgeClientError(detail, status_code=response.status_code)
        return response

    async def probe(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/probe",
            json={
                "host": host,
                "port": port,
                "username": username,
                "password": password,
            },
            secrets=(password,),
        )
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def create_stream(self, target: HikBridgeTarget) -> str:
        response = await self._request(
            "POST",
            "/streams",
            json={
                "host": target.host,
                "port": target.port,
                "username": target.username,
                "password": target.password,
                "channel": target.channel,
                "stream_type": target.stream_type,
            },
            secrets=(target.password,),
        )
        stream_id = str(response.json().get("stream_id") or "").strip()
        if not stream_id:
            raise HikBridgeClientError("HIK bridge returned no stream id")
        return stream_id

    def media_url(self, stream_id: str) -> str:
        return f"{self.base_url}/streams/{quote(stream_id, safe='')}/media"

    async def stop_stream(self, stream_id: str) -> None:
        await self._request("DELETE", f"/streams/{quote(stream_id, safe='')}")
