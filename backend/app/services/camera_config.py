from app.models.camera import Camera
from app.services.ffmpeg_builder import CameraRuntimeConfig
from app.services.media_adapter import resolve_media_source


def runtime_config(
    camera: Camera,
    *,
    align_segments_to_clock: bool | None = None,
) -> CameraRuntimeConfig:
    source = resolve_media_source(camera, "recording")
    return CameraRuntimeConfig(
        id=camera.id,
        name=camera.name,
        stream_uri=source.uri,
        timestamp_mode=camera.timestamp_mode,
        fps_num=camera.fps_num,
        fps_den=camera.fps_den,
        audio_codec=camera.audio_codec,
        sample_rate=camera.sample_rate,
        audio_frame_samples=camera.audio_frame_samples,
        media_source=source,
        align_segments_to_clock=align_segments_to_clock,
    )
