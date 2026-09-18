import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.camera import Camera
from app.models.detection_event import DetectionEvent
from app.models.motion import MotionEvent, MotionZone
from app.schemas.event_detection import (
    DetectionCapabilitySlot,
    DetectionEventRead,
    EventDetectionOverview,
    EventSourceRead,
)
from app.services.event_detection import event_source_registry
from app.services.event_detection.registry import (
    EventSourceConflict,
    EventSourceUnavailable,
    UnknownEventSource,
)
from app.services.motion_manager import motion_detection_manager  # noqa: F401 - compatibility hook

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


_CAPABILITY_TYPES = ("motion", "person", "vehicle", "intrusion", "tamper", "digital_input")


def _capability_slots(sources, enabled_source_ids: list[str]) -> list[DetectionCapabilitySlot]:
    slots: list[DetectionCapabilitySlot] = []
    for event_type in _CAPABILITY_TYPES:
        candidates = [
            source
            for source in sources
            if event_type in source.capabilities and source.status in {"available", "error"}
        ]
        enabled = next(
            (source for source in candidates if source.id in enabled_source_ids),
            None,
        )
        selected = enabled or (candidates[0] if candidates else None)
        if selected is not None:
            slots.append(
                DetectionCapabilitySlot(
                    event_type=event_type,
                    status=selected.status,
                    source_id=selected.id,
                    reason=selected.reason,
                )
            )
            continue

        if event_type in {"person", "vehicle"}:
            reason = "未发现摄像头原生能力，且未安装 AI Provider"
        elif event_type in {"tamper", "digital_input"}:
            reason = "当前摄像头未公布该原生事件能力"
        else:
            reason = "尚无可用 Provider"
        slots.append(
            DetectionCapabilitySlot(
                event_type=event_type,
                status="unavailable",
                reason=reason,
            )
        )
    return slots


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
        capability_slots=_capability_slots(sources, enabled_source_ids),
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
    except EventSourceConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EventSourceUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"legacy_metadata": raw}
    return value if isinstance(value, dict) else {"legacy_metadata": value}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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

    normalized: list[DetectionEventRead] = []

    include_motion = event_type in {None, "motion"} and provider in {None, "motion"}
    if include_motion:
        motion_statement = select(MotionEvent).where(
            MotionEvent.started_at <= end,
            MotionEvent.ended_at >= start,
        )
        if camera_id is not None:
            motion_statement = motion_statement.where(MotionEvent.camera_id == camera_id)
        motion_statement = motion_statement.order_by(
            MotionEvent.started_at.desc(),
            MotionEvent.id.desc(),
        ).limit(limit)
        motion_events = list(await db.scalars(motion_statement))

        zone_ids = {event.zone_id for event in motion_events if event.zone_id is not None}
        zone_names: dict[int, str] = {}
        if zone_ids:
            zones = await db.scalars(select(MotionZone).where(MotionZone.id.in_(zone_ids)))
            zone_names = {zone.id: zone.name for zone in zones}

        normalized.extend(
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
            for event in motion_events
        )

    include_native = provider != "motion"
    if include_native:
        native_statement = select(DetectionEvent).where(
            DetectionEvent.started_at <= end,
            DetectionEvent.ended_at >= start,
        )
        if camera_id is not None:
            native_statement = native_statement.where(DetectionEvent.camera_id == camera_id)
        if event_type is not None:
            native_statement = native_statement.where(DetectionEvent.event_type == event_type)
        if provider is not None:
            native_statement = native_statement.where(DetectionEvent.provider == provider)
        native_statement = native_statement.order_by(
            DetectionEvent.started_at.desc(),
            DetectionEvent.id.desc(),
        ).limit(limit)
        native_events = list(await db.scalars(native_statement))
        normalized.extend(
            DetectionEventRead(
                id=event.id,
                camera_id=event.camera_id,
                source_kind=event.source_kind,
                provider=event.provider,
                event_type=event.event_type,
                started_at=event.started_at,
                ended_at=event.ended_at,
                confidence=event.confidence,
                recording_id=event.recording_id,
                metadata=event.metadata_json or {},
            )
            for event in native_events
        )

    normalized.sort(
        key=lambda event: (_utc(event.started_at), int(event.id)),
        reverse=True,
    )
    return normalized[:limit]
