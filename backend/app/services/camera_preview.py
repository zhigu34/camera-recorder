import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal

from app.core.config import settings

PreviewStream = Literal["auto", "main", "sub"]


class CameraPreviewError(RuntimeError):
    pass


def infer_substream_path(main_path: str) -> str | None:
    """Compatibility helper; stream selection now belongs to stream_resolver."""

    if "/main" in main_path:
        return main_path.rsplit("/main", 1)[0] + "/sub" + main_path.rsplit("/main", 1)[1]
    if main_path.endswith("main"):
        return main_path[:-4] + "sub"
    return None


def resolve_preview_path(
    *,
    main_path: str,
    sub_path: str | None,
    stream: PreviewStream,
) -> tuple[str, Literal["main", "sub"]]:
    """Compatibility shim for callers/tests outside the camera API.

    Production camera preview resolves the complete URI through stream_resolver.
    """

    configured_sub = sub_path.strip() if sub_path else None
    inferred_sub = infer_substream_path(main_path)

    if stream == "main":
        return main_path, "main"
    if stream == "sub":
        selected = configured_sub or inferred_sub
        if not selected:
            raise CameraPreviewError("未配置子码流路径，且无法根据主码流路径自动推测")
        return selected, "sub"

    selected = configured_sub or inferred_sub
    if selected:
        return selected, "sub"
    return main_path, "main"


def build_preview_command(
    *,
    stream_uri: str,
    rtsp_timeout_us: int,
    fps: int,
    width: int,
) -> list[str]:
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
        stream_uri,
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"fps={fps},scale='min({width},iw)':-2",
        "-c:v",
        "mjpeg",
        "-q:v",
        "6",
        "-f",
        "mpjpeg",
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
class PreviewSession:
    process: asyncio.subprocess.Process
    first_chunk: bytes

    async def stream(self) -> AsyncIterator[bytes]:
        try:
            if self.first_chunk:
                yield self.first_chunk
            assert self.process.stdout is not None
            while True:
                chunk = await self.process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            await _stop_process(self.process)


async def open_mjpeg_preview(
    *,
    stream_uri: str,
    rtsp_timeout_us: int,
    fps: int,
    width: int,
) -> PreviewSession:
    command = build_preview_command(
        stream_uri=stream_uri,
        rtsp_timeout_us=rtsp_timeout_us,
        fps=fps,
        width=width,
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise CameraPreviewError("ffmpeg not found") from exc

    assert process.stdout is not None
    first_frame_timeout = max(8.0, rtsp_timeout_us / 1_000_000 + 3.0)
    try:
        first_chunk = await asyncio.wait_for(
            process.stdout.read(64 * 1024),
            timeout=first_frame_timeout,
        )
    except TimeoutError as exc:
        await _stop_process(process)
        raise CameraPreviewError("实时预览连接超时") from exc

    if not first_chunk:
        await _stop_process(process)
        raise CameraPreviewError("无法打开实时预览码流，请检查 RTSP 路径、账号和网络")

    return PreviewSession(process=process, first_chunk=first_chunk)
