import asyncio
from dataclasses import asdict, dataclass

from app.core.config import settings


@dataclass(slots=True)
class FFmpegCapabilities:
    ffmpeg_available: bool
    ffprobe_available: bool
    setts_available: bool
    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None


def _first_line(text: str) -> str | None:
    text = text.strip()
    return text.splitlines()[0] if text else None


async def _run(*args: str) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, "", "not found"

    stdout, stderr = await process.communicate()
    return process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def detect_ffmpeg_capabilities() -> FFmpegCapabilities:
    ffmpeg_rc, ffmpeg_out, ffmpeg_err = await _run(settings.ffmpeg_bin, "-version")
    ffprobe_rc, ffprobe_out, ffprobe_err = await _run(settings.ffprobe_bin, "-version")

    setts_available = False
    if ffmpeg_rc == 0:
        setts_rc, setts_out, setts_err = await _run(settings.ffmpeg_bin, "-hide_banner", "-h", "bsf=setts")
        setts_text = f"{setts_out}\n{setts_err}".lower()
        setts_available = setts_rc == 0 and "setts" in setts_text and "prescale" in setts_text

    return FFmpegCapabilities(
        ffmpeg_available=ffmpeg_rc == 0,
        ffprobe_available=ffprobe_rc == 0,
        setts_available=setts_available,
        ffmpeg_version=_first_line(ffmpeg_out or ffmpeg_err),
        ffprobe_version=_first_line(ffprobe_out or ffprobe_err),
    )


async def capabilities_dict() -> dict:
    return asdict(await detect_ffmpeg_capabilities())
