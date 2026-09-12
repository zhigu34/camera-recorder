from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.services.camera_probe import build_rtsp_url
from app.services.system_settings import RuntimeSettings


@dataclass(slots=True)
class CameraRuntimeConfig:
    id: int
    name: str
    ip: str
    rtsp_port: int
    username: str
    password: str
    rtsp_path: str
    timestamp_mode: str
    fps_num: int | None
    fps_den: int | None
    audio_codec: str | None
    sample_rate: int | None
    audio_frame_samples: int | None
    # None follows the global setting. Scheduled recordings can explicitly disable
    # wall-clock alignment so a 21:01-21:11 window is not split at 21:10.
    align_segments_to_clock: bool | None = None


class FFmpegCommandError(ValueError):
    pass


def _video_setts(camera: CameraRuntimeConfig) -> str:
    if not camera.fps_num or not camera.fps_den:
        raise FFmpegCommandError("reconstruct mode requires a detected FPS; run Probe first")
    time_base = f"{camera.fps_den}/{camera.fps_num}"
    return f"setts=ts=N:duration=1:time_base={time_base}:prescale=1"


def _audio_setts(camera: CameraRuntimeConfig) -> str | None:
    if not camera.audio_codec:
        return None
    if not camera.sample_rate or not camera.audio_frame_samples:
        raise FFmpegCommandError(
            "reconstruct mode requires detected audio sample_rate/frame_samples; run Probe first"
        )
    samples = camera.audio_frame_samples
    return (
        f"setts=ts=N*{samples}:duration={samples}:"
        f"time_base=1/{camera.sample_rate}:prescale=1"
    )


def build_record_command(
    camera: CameraRuntimeConfig,
    output_dir: Path,
    runtime: RuntimeSettings,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rtsp_url = build_rtsp_url(
        camera.ip,
        camera.rtsp_port,
        camera.username,
        camera.password,
        camera.rtsp_path,
    )

    input_fflags = "+discardcorrupt"
    if camera.timestamp_mode == "wallclock":
        input_fflags += "+genpts"

    command = [
        settings.ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        str(runtime.rtsp_timeout_us),
        "-fflags",
        input_fflags,
    ]

    if camera.timestamp_mode == "wallclock":
        command += ["-use_wallclock_as_timestamps", "1"]

    command += [
        "-i",
        rtsp_url,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
    ]

    if camera.timestamp_mode == "reconstruct":
        command += ["-bsf:v", _video_setts(camera)]
        audio_filter = _audio_setts(camera)
        if audio_filter:
            command += ["-bsf:a", audio_filter]

    command += [
        "-f",
        "segment",
        "-segment_format",
        "matroska",
        "-segment_time",
        str(runtime.segment_duration_seconds),
        "-reset_timestamps",
        "1",
        "-strftime",
        "1",
    ]

    align_to_clock = (
        runtime.align_segments_to_clock
        if camera.align_segments_to_clock is None
        else camera.align_segments_to_clock
    )
    if align_to_clock:
        command += ["-segment_atclocktime", "1"]

    command += [str(output_dir / "%Y-%m-%d_%H-%M-%S.mkv")]
    return command


def redact_command(command: list[str]) -> list[str]:
    redacted = command.copy()
    try:
        input_index = redacted.index("-i") + 1
        if input_index < len(redacted):
            redacted[input_index] = "rtsp://***:***@camera/stream"
    except ValueError:
        pass
    return redacted
