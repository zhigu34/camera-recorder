from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.recording import Recording
from app.schemas.recording import RecordingRead

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


@router.get("", response_model=list[RecordingRead])
async def list_recordings(
    camera_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    statement = select(Recording).order_by(Recording.started_at.desc(), Recording.id.desc())
    if camera_id is not None:
        statement = statement.where(Recording.camera_id == camera_id)
    result = await db.scalars(statement.limit(limit))
    return list(result)


@router.get("/{recording_id}", response_model=RecordingRead)
async def get_recording(recording_id: int, db: AsyncSession = Depends(get_db)):
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")
    return recording
