from app.core.security import decrypt_secret
from app.models.camera import Camera
from app.services.ffmpeg_builder import CameraRuntimeConfig


def runtime_config(
    camera: Camera,
    *,
    align_segments_to_clock: bool | None = None,
) -> CameraRuntimeConfig:
    return CameraRuntimeConfig(
        id=camera.id,
        name=camera.name,
        ip=camera.ip,
        rtsp_port=camera.rtsp_port,
        username=camera.username,
        password=decrypt_secret(camera.password_encrypted),
        rtsp_path=camera.rtsp_path,
        timestamp_mode=camera.timestamp_mode,
        fps_num=camera.fps_num,
        fps_den=camera.fps_den,
        audio_codec=camera.audio_codec,
        sample_rate=camera.sample_rate,
        audio_frame_samples=camera.audio_frame_samples,
        align_segments_to_clock=align_segments_to_clock,
    )
