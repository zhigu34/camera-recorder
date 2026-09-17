import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass

from app.core.config import settings
from app.services.camera_probe import build_rtsp_url

FrameCallback = Callable[[bytes], Awaitable[None]]


class JpegFrameParser:
    """Extract complete JPEG frames from an arbitrary byte stream."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        if chunk:
            self._buffer.extend(chunk)
        frames: list[bytes] = []
        while True:
            start = self._buffer.find(b"\xff\xd8")
            if start < 0:
                if len(self._buffer) > 1:
                    del self._buffer[:-1]
                break
            if start > 0:
                del self._buffer[:start]
            end = self._buffer.find(b"\xff\xd9", 2)
            if end < 0:
                break
            end += 2
            frames.append(bytes(self._buffer[:end]))
            del self._buffer[:end]
        return frames


def build_wall_preview_command(
    *,
    ip: str,
    port: int,
    username: str,
    password: str,
    rtsp_path: str,
    rtsp_timeout_us: int,
    fps: int,
    width: int,
) -> list[str]:
    url = build_rtsp_url(ip, port, username, password, rtsp_path)
    return [
        settings.ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        str(rtsp_timeout_us),
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-i",
        url,
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"fps={fps},scale='min({width},iw)':-2",
        "-c:v",
        "mjpeg",
        "-q:v",
        "7",
        "-f",
        "image2pipe",
        "pipe:1",
    ]


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except TimeoutError:
        process.kill()
        with suppress(Exception):
            await process.wait()


@dataclass(slots=True)
class WallPreviewSource:
    ip: str
    port: int
    username: str
    password: str
    rtsp_path: str
    rtsp_timeout_us: int
    fps: int
    width: int


async def _open_wall_process(source: WallPreviewSource) -> asyncio.subprocess.Process:
    command = build_wall_preview_command(
        ip=source.ip,
        port=source.port,
        username=source.username,
        password=source.password,
        rtsp_path=source.rtsp_path,
        rtsp_timeout_us=source.rtsp_timeout_us,
        fps=source.fps,
        width=source.width,
    )
    try:
        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found") from exc


class WallPreviewSession:
    def __init__(self, source: WallPreviewSource) -> None:
        self.source = source
        self._process: asyncio.subprocess.Process | None = None
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def _start(self) -> asyncio.subprocess.Process | None:
        async with self._close_lock:
            if self._closed:
                return None
            process = await _open_wall_process(self.source)
            self._process = process
            return process

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if self._process is not None:
                await _stop_process(self._process)

    async def stream(self, on_frame: FrameCallback) -> None:
        try:
            process = await self._start()
            if process is None:
                return
            assert process.stdout is not None
            parser = JpegFrameParser()
            read_timeout = max(8.0, self.source.rtsp_timeout_us / 1_000_000 + 3.0)

            while True:
                try:
                    chunk = await asyncio.wait_for(
                        process.stdout.read(64 * 1024),
                        timeout=read_timeout,
                    )
                except TimeoutError as exc:
                    if self._closed:
                        return
                    raise RuntimeError("实时预览连接超时") from exc
                if not chunk:
                    if self._closed:
                        return
                    if process.returncode is None:
                        await process.wait()
                    if self._closed:
                        return
                    raise RuntimeError("实时预览码流已结束")
                for frame in parser.feed(chunk):
                    await on_frame(frame)
                    read_timeout = 30.0
        finally:
            await self.close()


async def stream_preview_frames(source: WallPreviewSource, on_frame: FrameCallback) -> None:
    session = WallPreviewSession(source)
    await session.stream(on_frame)
