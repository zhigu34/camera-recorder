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

    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'camera.db'}"
    recordings_dir: Path = BASE_DIR / "recordings"
    staging_dir: Path = BASE_DIR / "staging"
    failed_dir: Path = BASE_DIR / "failed"
    logs_dir: Path = BASE_DIR / "logs"

    segment_duration_seconds: int = 600
    remux_concurrency: int = 2
    upload_concurrency: int = 2

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"


settings = Settings()
