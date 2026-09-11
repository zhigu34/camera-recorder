from app.api.cameras import router as cameras_router
from app.api.recordings import router as recordings_router
from app.api.recorder import router as recorder_router

__all__ = ["cameras_router", "recordings_router", "recorder_router"]
