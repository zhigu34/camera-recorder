from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_prefix="CAMREC_",
        extra="ignore",
    )

    # Deployment / secret settings only. User-facing runtime settings live in SQLite.
    secret_key: str = "change-me-before-exposing-this-service"

    data_dir: Path = BASE_DIR / "data"
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'camera.db'}"
    recordings_dir: Path = BASE_DIR / "recordings"
    staging_dir: Path = BASE_DIR / "staging"
    failed_dir: Path = BASE_DIR / "failed"
    logs_dir: Path = BASE_DIR / "logs"
    openlist_public_port: int = 5244
    hik_bridge_url: str = "http://hik-bridge:8100"
    internal_media_url: str = "http://127.0.0.1:8000"

    # Internal worker polling intervals are implementation details, not UI settings.
    segment_scan_interval_seconds: float = 3.0
    segment_finalize_grace_seconds: float = 3.0
    probe_timeout_seconds: float = 12.0
    upload_scan_interval_seconds: float = 10.0

    # Binary paths are fixed by the container in production.
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"


settings = Settings()
