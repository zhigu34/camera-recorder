from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.recording import Recording
from app.services.recording_playback import recording_playback_manager

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


@router.post("/{recording_id}/playback/cancel")
async def cancel_playback_proxy(
    recording_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="recording not found")
    return await recording_playback_manager.cancel(recording_id)
