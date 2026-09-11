import httpx
import pytest

from app.services.cloud_stream import CloudStreamHandle, OpenListCloudStreamer


@pytest.mark.asyncio
async def test_public_redirect_allows_external_provider_url():
    client = httpx.AsyncClient()
    request = httpx.Request("GET", "http://openlist:5244/dav/115/recording.mp4")
    response = httpx.Response(
        302,
        headers={"location": "https://cdn.example.test/video.mp4?token=abc"},
        request=request,
    )
    handle = CloudStreamHandle(client=client, response=response)

    assert (
        OpenListCloudStreamer.public_redirect(handle)
        == "https://cdn.example.test/video.mp4?token=abc"
    )
    await handle.close()


@pytest.mark.asyncio
async def test_public_redirect_keeps_internal_openlist_path_server_side():
    client = httpx.AsyncClient()
    request = httpx.Request("GET", "http://openlist:5244/dav/115/recording.mp4")
    response = httpx.Response(
        302,
        headers={"location": "http://openlist:5244/d/115/recording.mp4?sign=x"},
        request=request,
    )
    handle = CloudStreamHandle(client=client, response=response)

    assert OpenListCloudStreamer.public_redirect(handle) is None
    await handle.close()


@pytest.mark.asyncio
async def test_range_proxy_preserves_media_headers():
    client = httpx.AsyncClient()
    request = httpx.Request("GET", "http://openlist:5244/dav/115/recording.mp4")
    response = httpx.Response(
        206,
        headers={
            "content-type": "video/mp4",
            "content-length": "4",
            "content-range": "bytes 0-3/100",
            "accept-ranges": "bytes",
            "etag": '"abc"',
        },
        content=b"data",
        request=request,
    )
    handle = CloudStreamHandle(client=client, response=response)

    headers = handle.response_headers()

    assert headers["Content-Range"] == "bytes 0-3/100"
    assert headers["Accept-Ranges"] == "bytes"
    assert headers["Content-Length"] == "4"
    assert headers["Content-Type"] == "video/mp4"
    assert headers["X-Cloud-Playback"] == "openlist-range-proxy"
    await handle.close()
