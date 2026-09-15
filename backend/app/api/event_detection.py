import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.camera import Camera
from app.models.motion import MotionEvent, MotionZone
from app.schemas.event_detection import (
    DetectionCapabilitySlot,
    DetectionEventRead,
    EventDetectionOverview,
    EventSourceRead,
)
from app.services.event_detection import event_source_registry
from app.services.event_detection.registry import UnknownEventSource
from app.services.motion_manager import motion_detection_manager

router = APIRouter(tags=["event-detection"])


async def _camera_or_404(camera_id: int, db: AsyncSession) -> Camera:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


def _adapter_or_404(source_id: str):
    try:
        return event_source_registry.get(source_id)
    except UnknownEventSource as exc:
        raise HTTPException(status_code=404, detail="event source not found") from exc


def _capability_slots() -> list[DetectionCapabilitySlot]:
    return [
        DetectionCapabilitySlot(
            event_type="motion",
            status="available",
            source_id="local.motion",
        ),
        DetectionCapabilitySlot(
            event_type="person",
            status="unavailable",
            reason="未安装 AI Provider",
        ),
        DetectionCapabilitySlot(
            event_type="vehicle",
            status="unavailable",
            reason="未安装 AI Provider",
        ),
        DetectionCapabilitySlot(
            event_type="intrusion",
            status="unavailable",
            reason="尚无可用 Provider",
        ),
    ]


@router.get(
    "/api/cameras/{camera_id}/event-detection",
    response_model=EventDetectionOverview,
)
async def get_event_detection_overview(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
):
    camera = await _camera_or_404(camera_id, db)
    sources = []
    enabled_source_ids: list[str] = []
    for source_id in event_source_registry.ids():
        adapter = event_source_registry.get(source_id)
        source = await adapter.read(camera, db)
        sources.append(source.descriptor)
        if source.config.get("enabled") is True:
            enabled_source_ids.append(source_id)
    return EventDetectionOverview(
        camera=camera,
        sources=sources,
        capability_slots=_capability_slots(),
        enabled_source_ids=enabled_source_ids,
    )


@router.get(
    "/api/cameras/{camera_id}/event-detection/sources/{source_id}",
    response_model=EventSourceRead,
)
async def get_event_detection_source(
    camera_id: int,
    source_id: str,
    db: AsyncSession = Depends(get_db),
):
    camera = await _camera_or_404(camera_id, db)
    adapter = _adapter_or_404(source_id)
    return await adapter.read(camera, db)


@router.put(
    "/api/cameras/{camera_id}/event-detection/sources/{source_id}",
    response_model=EventSourceRead,
)
async def update_event_detection_source(
    camera_id: int,
    source_id: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    camera = await _camera_or_404(camera_id, db)
    adapter = _adapter_or_404(source_id)
    try:
        return await adapter.update(camera, payload, db)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"legacy_metadata": raw}
    return value if isinstance(value, dict) else {"legacy_metadata": value}


@router.get("/api/detection-events", response_model=list[DetectionEventRead])
async def list_detection_events(
    start: datetime = Query(...),
    end: datetime = Query(...),
    camera_id: int | None = Query(default=None, gt=0),
    event_type: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    if start > end:
        raise HTTPException(status_code=422, detail="start must not be after end")
    if camera_id is not None:
        await _camera_or_404(camera_id, db)
    if event_type not in {None, "motion"} or provider not in {None, "motion"}:
        return []

    statement = select(MotionEvent).where(
        MotionEvent.started_at <= end,
        MotionEvent.ended_at >= start,
    )
    if camera_id is not None:
        statement = statement.where(MotionEvent.camera_id == camera_id)
    statement = statement.order_by(MotionEvent.started_at.desc(), MotionEvent.id.desc()).limit(limit)
    events = list(await db.scalars(statement))

    zone_ids = {event.zone_id for event in events if event.zone_id is not None}
    zone_names: dict[int, str] = {}
    if zone_ids:
        zones = await db.scalars(select(MotionZone).where(MotionZone.id.in_(zone_ids)))
        zone_names = {zone.id: zone.name for zone in zones}

    return [
        DetectionEventRead(
            id=event.id,
            camera_id=event.camera_id,
            source_kind="local",
            provider="motion",
            event_type="motion",
            started_at=event.started_at,
            ended_at=event.ended_at,
            confidence=event.peak_score,
            zone_id=event.zone_id,
            zone_name=zone_names.get(event.zone_id) if event.zone_id is not None else None,
            recording_id=event.recording_id,
            snapshot_url=(
                f"/api/motion-events/{event.id}/snapshot" if event.snapshot_path else None
            ),
            metadata=_parse_metadata(event.metadata_json),
        )
        for event in events
    ]
