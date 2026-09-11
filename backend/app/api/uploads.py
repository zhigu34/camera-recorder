import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal, get_db
from app.models.upload import UploadTask
from app.schemas.upload import UploadTaskRead
from app.services.upload_manager import upload_manager

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
ws_router = APIRouter(tags=["uploads"])


def _serialize_task(task: UploadTask) -> dict:
    return UploadTaskRead.model_validate(task).model_dump(mode="json")


def _task_signature(task: UploadTask) -> tuple:
    return (
        task.status,
        task.retry_count,
        task.last_error,
        task.started_at,
        task.completed_at,
        task.next_retry_at,
        task.updated_at,
    )


async def _status_payload(db: AsyncSession) -> dict:
    counts: dict[str, int] = {}
    rows = list(await db.scalars(select(UploadTask)))
    for task in rows:
        counts[task.status] = counts.get(task.status, 0) + 1
    status = await upload_manager.status()
    return {**status, "counts": counts}


async def _recent_tasks(db: AsyncSession, limit: int = 1000) -> list[UploadTask]:
    return list(
        await db.scalars(
            select(UploadTask).order_by(UploadTask.id.desc()).limit(limit)
        )
    )


@router.get("")
async def upload_status(db: AsyncSession = Depends(get_db)):
    return await _status_payload(db)


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


@ws_router.websocket("/ws/uploads")
async def upload_websocket(websocket: WebSocket) -> None:
    """Push upload task/status changes without repeatedly reloading large REST lists."""

    await websocket.accept()
    try:
        async with SessionLocal() as session:
            tasks = await _recent_tasks(session)
            status = await _status_payload(session)

        signatures = {task.id: _task_signature(task) for task in tasks}
        last_status = status
        await websocket.send_json(
            {
                "type": "uploads.snapshot",
                "tasks": [_serialize_task(task) for task in tasks],
                "status": status,
            }
        )

        status_ticks = 0
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                if message.get("type") == "websocket.disconnect":
                    return
            except TimeoutError:
                pass

            async with SessionLocal() as session:
                current_tasks = await _recent_tasks(session)
            current_signatures = {
                task.id: _task_signature(task) for task in current_tasks
            }
            changed = [
                task
                for task in current_tasks
                if signatures.get(task.id) != current_signatures[task.id]
            ]
            removed_ids = sorted(set(signatures) - set(current_signatures))
            status_ticks += 1

            next_status = last_status
            if changed or removed_ids or status_ticks >= 5:
                async with SessionLocal() as session:
                    next_status = await _status_payload(session)
                status_ticks = 0

            if changed or removed_ids or next_status != last_status:
                await websocket.send_json(
                    {
                        "type": "uploads.delta",
                        "tasks": [_serialize_task(task) for task in changed],
                        "removed_ids": removed_ids,
                        "status": next_status,
                    }
                )

            signatures = current_signatures
            last_status = next_status
    except RuntimeError:
        # A disconnect can race with the next send/receive cycle.
        return


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
