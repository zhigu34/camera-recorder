from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.playback_client_metrics import playback_client_metrics
from app.services.playback_prefetch import playback_prefetch_manager

router = APIRouter(prefix="/api/playback", tags=["playback"])


class BrowserPlaybackMetric(BaseModel):
    attempt_id: str = Field(min_length=1, max_length=80)
    recording_id: int = Field(gt=0)
    event: Literal["decode_ready", "first_frame", "startup_error", "playback_error"]
    duration_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    metadata_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    loaded_data_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    canplay_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    playing_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    browser: str = Field(default="unknown", min_length=1, max_length=32)
    browser_version: str = Field(default="unknown", min_length=1, max_length=16)
    platform: str = Field(default="unknown", min_length=1, max_length=32)
    codec: str = Field(default="unknown", min_length=1, max_length=16)
    playback_mode: str = Field(default="unknown", min_length=1, max_length=32)
    source_kind: str = Field(default="unknown", min_length=1, max_length=32)
    signal: str = Field(default="unknown", min_length=1, max_length=32)
    hevc_hint: str = Field(default="unknown", min_length=1, max_length=32)
    media_error_code: int | None = Field(default=None, ge=1, le=4)
    ready_state: int | None = Field(default=None, ge=0, le=4)
    network_state: int | None = Field(default=None, ge=0, le=3)


@router.get("/metrics")
async def playback_metrics() -> dict:
    """Return in-memory backend and real-browser playback quality metrics."""

    return {
        **playback_prefetch_manager.snapshot(),
        "client": playback_client_metrics.snapshot(),
    }


@router.post("/metrics/client", status_code=202)
async def record_browser_playback_metric(metric: BrowserPlaybackMetric) -> dict[str, bool]:
    """Accept coarse browser playback timing/outcome telemetry.

    The browser sends no media URL, OpenList token, credential, IP address, or full
    user-agent string. Samples stay in memory and disappear on service restart.
    """

    playback_client_metrics.record(metric.model_dump())
    return {"accepted": True}
