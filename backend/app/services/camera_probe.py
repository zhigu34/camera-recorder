import asyncio
import json
from fractions import Fraction
from urllib.parse import quote

from app.core.config import settings
from app.services.media_input import media_input_from_uri


class CameraProbeError(RuntimeError):
    pass


def build_rtsp_url(
    ip: str,
    port: int,
    username: str,
    password: str,
    rtsp_path: str,
) -> str:
    path = rtsp_path if rtsp_path.startswith("/") else f"/{rtsp_path}"
    user = quote(username, safe="")
    secret = quote(password, safe="")
    return f"rtsp://{user}:{secret}@{ip}:{port}{path}"


def _ratio(value: str | None) -> tuple[int | None, int | None, float | None]:
    if not value or value == "0/0":
        return None, None, None
    try:
        ratio = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None, None, None
    if ratio.denominator == 0:
        return None, None, None
    return ratio.numerator, ratio.denominator, float(ratio)


async def probe_stream_uri(*, stream_uri: str, rtsp_timeout_us: int) -> dict:
    """Probe video and audio from an already-resolved media URI."""

    try:
        media_input = media_input_from_uri(stream_uri, timeout_us=rtsp_timeout_us)
    except ValueError as exc:
        raise CameraProbeError(str(exc)) from exc

    command = [
        settings.ffprobe_bin,
        "-v",
        "error",
        *media_input.transport_args,
        "-show_streams",
        "-of",
        "json",
        media_input.uri,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise CameraProbeError("ffprobe not found") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=settings.probe_timeout_seconds
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise CameraProbeError("media probe timed out") from exc

    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip() or "ffprobe failed"
        raise CameraProbeError(message[-1000:])

    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CameraProbeError("invalid ffprobe JSON") from exc

    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)

    if not video:
        raise CameraProbeError("media stream has no video track")

    fps_source = video.get("avg_frame_rate")
    if not fps_source or fps_source == "0/0":
        fps_source = video.get("r_frame_rate")
    fps_num, fps_den, fps = _ratio(fps_source)

    audio_codec = audio.get("codec_name") if audio else None
    audio_frame_samples = None
    if audio:
        raw_frame_size = audio.get("frame_size")
        if raw_frame_size:
            try:
                audio_frame_samples = int(raw_frame_size)
            except (TypeError, ValueError):
                audio_frame_samples = None
        if not audio_frame_samples and audio_codec == "aac":
            audio_frame_samples = 1024

    return {
        "ok": True,
        "video_codec": video.get("codec_name"),
        "video_profile": video.get("profile"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps_num": fps_num,
        "fps_den": fps_den,
        "fps": fps,
        "pixel_format": video.get("pix_fmt"),
        "has_b_frames": video.get("has_b_frames"),
        "video_time_base": video.get("time_base"),
        "audio_codec": audio_codec,
        "audio_profile": audio.get("profile") if audio else None,
        "sample_rate": int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        "channels": audio.get("channels") if audio else None,
        "audio_frame_samples": audio_frame_samples,
    }


async def probe_camera_media(camera, *, rtsp_timeout_us: int) -> dict:
    """Probe a camera through its registered media adapter."""

    # Local import avoids a module cycle: the manual adapter reuses build_rtsp_url.
    from app.services.stream_resolver import resolve_stream

    try:
        resolved = resolve_stream(camera, "recording", preferred="main")
    except Exception as exc:
        raise CameraProbeError(f"media source resolution failed: {exc}") from exc
    return await probe_stream_uri(
        stream_uri=resolved.uri,
        rtsp_timeout_us=rtsp_timeout_us,
    )


async def probe_camera(
    *,
    ip: str,
    port: int,
    username: str,
    password: str,
    rtsp_path: str,
    rtsp_timeout_us: int,
) -> dict:
    """Compatibility wrapper that resolves the legacy RTSP fields to one URI."""

    return await probe_stream_uri(
        stream_uri=build_rtsp_url(ip, port, username, password, rtsp_path),
        rtsp_timeout_us=rtsp_timeout_us,
    )