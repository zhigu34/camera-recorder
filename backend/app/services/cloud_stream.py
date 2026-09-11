from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.services.system_settings import RuntimeSettings
from app.services.upload_manager import OpenListWebDAVProvider, WebDAVError

_REDIRECT_CODES = {301, 302, 303, 307, 308}
_FORWARD_RESPONSE_HEADERS = (
    "accept-ranges",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
)


@dataclass(slots=True)
class CloudStreamHandle:
    client: httpx.AsyncClient
    response: httpx.Response

    async def close(self) -> None:
        await self.response.aclose()
        await self.client.aclose()

    async def iter_bytes(self):
        try:
            async for chunk in self.response.aiter_bytes(256 * 1024):
                if chunk:
                    yield chunk
        finally:
            await self.close()

    def response_headers(self) -> dict[str, str]:
        headers = {
            name.title(): self.response.headers[name]
            for name in _FORWARD_RESPONSE_HEADERS
            if name in self.response.headers
        }
        headers["X-Accel-Buffering"] = "no"
        headers["X-Cloud-Playback"] = "openlist-range-proxy"
        return headers


class OpenListCloudStreamer:
    """Bridge archived objects without exposing OpenList credentials.

    OpenList WebDAV can either proxy bytes itself (200/206) or return a 30x
    provider direct link. Public cross-host redirects are passed to the browser so
    media bytes bypass camera-recorder. Internal/relative redirects stay server
    side and are proxied with HTTP Range support.
    """

    @staticmethod
    def provider(runtime: RuntimeSettings) -> OpenListWebDAVProvider:
        return OpenListWebDAVProvider(runtime)

    async def open(
        self,
        remote_path: str,
        runtime: RuntimeSettings,
        *,
        range_header: str | None = None,
        if_range_header: str | None = None,
        follow_redirects: bool = False,
    ) -> CloudStreamHandle:
        provider = self.provider(runtime)
        if not provider.configured:
            raise WebDAVError("OpenList WebDAV credentials are not configured")

        headers: dict[str, str] = {}
        if range_header:
            headers["Range"] = range_header
        if if_range_header:
            headers["If-Range"] = if_range_header

        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0)
        client = httpx.AsyncClient(
            auth=httpx.BasicAuth(provider.username, provider.password),
            timeout=timeout,
            follow_redirects=follow_redirects,
        )
        request = client.build_request("GET", provider._url(remote_path), headers=headers)
        try:
            response = await client.send(request, stream=True)
        except Exception:
            await client.aclose()
            raise

        if response.status_code not in {200, 206, *_REDIRECT_CODES}:
            body = await response.aread()
            await response.aclose()
            await client.aclose()
            raise WebDAVError(
                f"GET {remote_path} failed: HTTP {response.status_code} "
                f"{body[:500].decode(errors='replace')}"
            )
        return CloudStreamHandle(client=client, response=response)

    @staticmethod
    def public_redirect(handle: CloudStreamHandle) -> str | None:
        response = handle.response
        if response.status_code not in _REDIRECT_CODES:
            return None
        location = response.headers.get("location")
        if not location:
            return None

        absolute = urljoin(str(response.url), location)
        target = urlparse(absolute)
        source = urlparse(str(response.url))
        if not target.scheme or not target.netloc:
            return None

        # A redirect back to the same OpenList host may be a /d or /p path that
        # is only reachable inside Docker. Keep it server-side. A provider/CDN
        # host is suitable for browser redirect and avoids relaying media bytes.
        if target.hostname == source.hostname and target.port == source.port:
            return None
        if target.hostname in {"openlist", "localhost", "127.0.0.1", "::1"}:
            return None
        return absolute


openlist_cloud_streamer = OpenListCloudStreamer()
