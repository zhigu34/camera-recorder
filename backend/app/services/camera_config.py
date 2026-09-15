from app.models.camera import Camera
from app.services.ffmpeg_builder import CameraRuntimeConfig
from app.services.stream_resolver import resolve_stream


def runtime_config(
    camera: Camera,
    *,
    align_segments_to_clock: bool | None = None,
) -> CameraRuntimeConfig:
    stream = resolve_stream(camera, "recording")
    return CameraRuntimeConfig(
        id=camera.id,
        name=camera.name,
        stream_uri=stream.uri,
        timestamp_mode=camera.timestamp_mode,
        fps_num=camera.fps_num,
        fps_den=camera.fps_den,
        audio_codec=camera.audio_codec,
        sample_rate=camera.sample_rate,
        audio_frame_samples=camera.audio_frame_samples,
        align_segments_to_clock=align_segments_to_clock,
    )
