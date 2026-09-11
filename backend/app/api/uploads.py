from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.upload import UploadTask
from app.schemas.upload import UploadTaskRead
from app.services.upload_manager import upload_manager

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.get("")
async def upload_status(db: AsyncSession = Depends(get_db)):
    counts: dict[str, int] = {}
    rows = list(await db.scalars(select(UploadTask)))
    for task in rows:
        counts[task.status] = counts.get(task.status, 0) + 1
    status = await upload_manager.status()
    return {**status, "counts": counts}


@router.get("/tasks", response_model=list[UploadTaskRead])
async def list_upload_tasks(
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    statement = select(UploadTask).order_by(UploadTask.id.desc())
    if status:
        statement = statement.where(UploadTask.status == status)
    result = await db.scalars(statement.limit(limit))
    return list(result)


@router.post("/tasks/{task_id}/retry", response_model=dict)
async def retry_upload(task_id: int):
    if not await upload_manager.retry(task_id):
        raise HTTPException(status_code=404, detail="upload task not found")
    return {"status": "pending", "task_id": task_id}


@router.post("/scan", response_model=dict)
async def scan_uploads():
    status = await upload_manager.status()
    if not status["active"]:
        raise HTTPException(
            status_code=409,
            detail="upload is disabled or OpenList WebDAV credentials are not configured",
        )
    await upload_manager.scan_once()
    return {"status": "ok"}
