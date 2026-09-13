from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.camera import Camera
from app.models.recording_export import ExportArtifact, ExportJob
from app.schemas.recording_export import (
    ExportArtifactRead,
    ExportCreateRequest,
    ExportGroupRead,
    ExportIntervalRead,
    ExportJobRead,
    ExportRangeAnalysisRead,
    ExportRangeRequest,
)
from app.services.recording_export import (
    ExportProcessError,
    ExportRangeAnalysis,
    _safe_under_export_root,
    analyze_recording_range,
    recording_export_manager,
)

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _interval_payload(item) -> ExportIntervalRead:
    return ExportIntervalRead(
        start_at=item.start_at,
        end_at=item.end_at,
        duration=item.duration,
    )


def _analysis_payload(camera_id: int, analysis: ExportRangeAnalysis) -> ExportRangeAnalysisRead:
    return ExportRangeAnalysisRead(
        camera_id=camera_id,
        requested_start_at=analysis.requested_start_at,
        requested_end_at=analysis.requested_end_at,
        recording_count=analysis.recording_count,
        unavailable_count=analysis.unavailable_count,
        requested_duration=analysis.requested_duration,
        covered_duration=analysis.covered_duration,
        continuous_groups=[
            ExportGroupRead(
                start_at=group.start_at,
                end_at=group.end_at,
                duration=group.duration,
                recording_ids=group.recording_ids,
            )
            for group in analysis.groups
        ],
        gaps=[_interval_payload(item) for item in analysis.gaps],
        unavailable_intervals=[_interval_payload(item) for item in analysis.unavailable_intervals],
        exportable=analysis.exportable,
    )


async def _camera_or_404(camera_id: int, db: AsyncSession) -> Camera:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


async def _job_or_404(job_id: int, db: AsyncSession) -> ExportJob:
    job = await db.get(ExportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="export job not found")
    return job


@router.post("/analyze", response_model=ExportRangeAnalysisRead)
async def analyze_export_range(
    payload: ExportRangeRequest,
    db: AsyncSession = Depends(get_db),
) -> ExportRangeAnalysisRead:
    await _camera_or_404(payload.camera_id, db)
    analysis = await analyze_recording_range(
        db,
        payload.camera_id,
        payload.start_at,
        payload.end_at,
    )
    return _analysis_payload(payload.camera_id, analysis)


@router.get("", response_model=list[ExportJobRead])
async def list_export_jobs(
    camera_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[ExportJob]:
    statement = select(ExportJob)
    if camera_id is not None:
        statement = statement.where(ExportJob.camera_id == camera_id)
    statement = statement.order_by(ExportJob.created_at.desc(), ExportJob.id.desc()).limit(limit)
    return list(await db.scalars(statement))


@router.post("", response_model=ExportJobRead, status_code=status.HTTP_201_CREATED)
async def create_export_job(
    payload: ExportCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> ExportJob:
    await _camera_or_404(payload.camera_id, db)
    analysis = await analyze_recording_range(
        db,
        payload.camera_id,
        payload.start_at,
        payload.end_at,
    )
    if not analysis.exportable:
        raise HTTPException(
            status_code=409,
            detail="requested range has no locally available recordings to export",
        )

    job = ExportJob(
        camera_id=payload.camera_id,
        requested_start_at=payload.start_at,
        requested_end_at=payload.end_at,
        export_mode=payload.export_mode,
        gap_policy=payload.gap_policy,
        package_mode=payload.package_mode,
        status="pending",
        progress=0.0,
        gap_count=len(analysis.gaps),
        requested_duration=analysis.requested_duration,
        covered_duration=analysis.covered_duration,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await recording_export_manager.enqueue(job.id)
    return job


@router.get("/{job_id}", response_model=ExportJobRead)
async def get_export_job(job_id: int, db: AsyncSession = Depends(get_db)) -> ExportJob:
    return await _job_or_404(job_id, db)


@router.get("/{job_id}/artifacts", response_model=list[ExportArtifactRead])
async def list_export_artifacts(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ExportArtifact]:
    await _job_or_404(job_id, db)
    return list(
        await db.scalars(
            select(ExportArtifact)
            .where(ExportArtifact.export_job_id == job_id)
            .order_by(ExportArtifact.segment_index.asc().nullsfirst(), ExportArtifact.id.asc())
        )
    )


@router.get("/{job_id}/artifacts/{artifact_id}/download")
async def download_export_artifact(
    job_id: int,
    artifact_id: int,
    db: AsyncSession = Depends(get_db),
):
    job = await _job_or_404(job_id, db)
    artifact = await db.get(ExportArtifact, artifact_id)
    if artifact is None or artifact.export_job_id != job.id:
        raise HTTPException(status_code=404, detail="export artifact not found")

    now = datetime.now(timezone.utc)
    expires_at = job.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now or job.status == "expired":
            raise HTTPException(status_code=410, detail="export artifact has expired")
    if job.status != "ready":
        raise HTTPException(status_code=409, detail="export job is not ready")

    path = Path(artifact.path)
    try:
        path = _safe_under_export_root(path)
    except ExportProcessError as exc:
        raise HTTPException(status_code=403, detail="export artifact path is not allowed") from exc
    try:
        available = path.is_file() and path.stat().st_size > 0
    except OSError:
        available = False
    if not available:
        raise HTTPException(status_code=410, detail="export artifact is no longer available")

    media_type = "application/zip" if artifact.kind == "zip" else "video/mp4"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={"Cache-Control": "private, no-store"},
    )
