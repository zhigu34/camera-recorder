from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.services.ffmpeg_capabilities import capabilities_dict


@asynccontextmanager
async def lifespan(_: FastAPI):
    for path in (
        settings.recordings_dir,
        settings.staging_dir,
        settings.failed_dir,
        settings.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system/status")
async def system_status() -> dict:
    return {
        "app": settings.app_name,
        "segment_duration_seconds": settings.segment_duration_seconds,
        "ffmpeg": await capabilities_dict(),
    }
