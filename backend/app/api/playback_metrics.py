from fastapi import APIRouter

from app.services.playback_prefetch import playback_prefetch_manager

router = APIRouter(prefix="/api/playback", tags=["playback"])


@router.get("/metrics")
async def playback_metrics() -> dict:
    """Return in-memory prefetch probe and backend playback response metrics."""

    return playback_prefetch_manager.snapshot()
