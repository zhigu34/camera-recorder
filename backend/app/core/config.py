from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_prefix="CAMREC_",
        extra="ignore",
    )

    app_name: str = "Camera Recorder"
    debug: bool = False
    secret_key: str = "change-me-before-exposing-this-service"

    data_dir: Path = BASE_DIR / "data"
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'camera.db'}"
    recordings_dir: Path = BASE_DIR / "recordings"
    staging_dir: Path = BASE_DIR / "staging"
    failed_dir: Path = BASE_DIR / "failed"
    logs_dir: Path = BASE_DIR / "logs"

    segment_duration_seconds: int = 600
    segment_scan_interval_seconds: float = 3.0
    segment_finalize_grace_seconds: float = 3.0
    remux_concurrency: int = 2
    upload_concurrency: int = 2

    rtsp_timeout_us: int = 5_000_000
    probe_timeout_seconds: float = 12.0
    auto_start_enabled: bool = True
    align_segments_to_clock: bool = True

    upload_enabled: bool = False
    upload_scan_interval_seconds: float = 10.0
    upload_retry_max: int = 8
    webdav_url: str = "http://openlist:5244/dav/115"
    webdav_root: str = "监控录像"
    webdav_username: str = "admin"
    webdav_password: str = ""
    local_retention_hours: int = 48

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"


settings = Settings()
