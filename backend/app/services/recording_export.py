from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zipfile import ZIP_STORED, ZipFile

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.recording import Recording
from app.models.recording_export import ExportArtifact, ExportJob

logger = logging.getLogger(__name__)

EXPORT_TTL = timedelta(hours=24)
GAP_TOLERANCE_SECONDS = 1.0


class ExportProcessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportSourceSlice:
    recording_id: int
    started_at: datetime
    ended_at: datetime
    path: Path
    available: bool = True


@dataclass
class ExportInterval:
    start_at: datetime
    end_at: datetime

    @property
    def duration(self) -> float:
        return max(0.0, (self.end_at - self.start_at).total_seconds())


@dataclass
class ExportGroup(ExportInterval):
    recording_ids: list[int] = field(default_factory=list)
    sources: list[ExportSourceSlice] = field(default_factory=list)


@dataclass(frozen=True)
class ExportRangeAnalysis:
    requested_start_at: datetime
    requested_end_at: datetime
    groups: list[ExportGroup]
    gaps: list[ExportInterval]
    unavailable_intervals: list[ExportInterval]
    unavailable_count: int

    @property
    def requested_duration(self) -> float:
        return max(0.0, (self.requested_end_at - self.requested_start_at).total_seconds())

    @property
    def covered_duration(self) -> float:
        return sum(group.duration for group in self.groups)

    @property
    def recording_count(self) -> int:
        return sum(len(group.recording_ids) for group in self.groups)

    @property
    def exportable(self) -> bool:
        return bool(self.groups)


def _clip_interval(
    start: datetime,
    end: datetime,
    lower: datetime,
    upper: datetime,
) -> ExportInterval | None:
    clipped_start = max(start, lower)
    clipped_end = min(end, upper)
    if clipped_end <= clipped_start:
        return None
    return ExportInterval(clipped_start, clipped_end)


def _merge_intervals(intervals: Iterable[ExportInterval]) -> list[ExportInterval]:
    ordered = sorted(intervals, key=lambda item: (item.start_at, item.end_at))
    merged: list[ExportInterval] = []
    for item in ordered:
        if not merged or item.start_at > merged[-1].end_at:
            merged.append(item)
            continue
        previous = merged[-1]
        merged[-1] = ExportInterval(previous.start_at, max(previous.end_at, item.end_at))
    return merged


def analyze_source_slices(
    sources: Iterable[ExportSourceSlice],
    requested_start_at: datetime,
    requested_end_at: datetime,
    gap_tolerance_seconds: float = GAP_TOLERANCE_SECONDS,
) -> ExportRangeAnalysis:
    if requested_end_at <= requested_start_at:
        raise ValueError("requested_end_at must be later than requested_start_at")

    tolerance = timedelta(seconds=max(0.0, gap_tolerance_seconds))
    available: list[tuple[ExportSourceSlice, ExportInterval]] = []
    unavailable: list[ExportInterval] = []
    unavailable_count = 0

    for source in sources:
        clipped = _clip_interval(
            source.started_at,
            source.ended_at,
            requested_start_at,
            requested_end_at,
        )
        if clipped is None:
            continue
        if not source.available:
            unavailable_count += 1
            unavailable.append(clipped)
            continue
        available.append((source, clipped))

    available.sort(key=lambda item: (item[1].start_at, item[1].end_at, item[0].recording_id))
    groups: list[ExportGroup] = []
    for source, clipped in available:
        if not groups or clipped.start_at > groups[-1].end_at + tolerance:
            groups.append(
                ExportGroup(
                    start_at=clipped.start_at,
                    end_at=clipped.end_at,
                    recording_ids=[source.recording_id],
                    sources=[source],
                )
            )
            continue
        group = groups[-1]
        group.end_at = max(group.end_at, clipped.end_at)
        group.recording_ids.append(source.recording_id)
        group.sources.append(source)

    gaps: list[ExportInterval] = []
    cursor = requested_start_at
    for group in groups:
        if group.start_at > cursor:
            gap = ExportInterval(cursor, group.start_at)
            if cursor == requested_start_at or gap.duration > gap_tolerance_seconds:
                gaps.append(gap)
        cursor = max(cursor, group.end_at)
    if cursor < requested_end_at:
        gaps.append(ExportInterval(cursor, requested_end_at))

    return ExportRangeAnalysis(
        requested_start_at=requested_start_at,
        requested_end_at=requested_end_at,
        groups=groups,
        gaps=gaps,
        unavailable_intervals=_merge_intervals(unavailable),
        unavailable_count=unavailable_count,
    )


def _normalize_db_datetime(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is not None:
        return value.astimezone(reference.tzinfo)
    return value


async def analyze_recording_range(
    session: AsyncSession,
    camera_id: int,
    requested_start_at: datetime,
    requested_end_at: datetime,
    gap_tolerance_seconds: float = GAP_TOLERANCE_SECONDS,
) -> ExportRangeAnalysis:
    recordings = list(
        await session.scalars(
            select(Recording)
            .where(
                Recording.camera_id == camera_id,
                Recording.status == "ready",
                Recording.started_at.is_not(None),
                Recording.ended_at.is_not(None),
                Recording.started_at < requested_end_at,
                Recording.ended_at > requested_start_at,
            )
            .order_by(Recording.started_at.asc(), Recording.id.asc())
        )
    )
    sources: list[ExportSourceSlice] = []
    for recording in recordings:
        if recording.started_at is None or recording.ended_at is None:
            continue
        path = Path(recording.mp4_path)
        try:
            available = path.is_file() and path.stat().st_size > 0
        except OSError:
            available = False
        sources.append(
            ExportSourceSlice(
                recording_id=recording.id,
                started_at=_normalize_db_datetime(recording.started_at, requested_start_at),
                ended_at=_normalize_db_datetime(recording.ended_at, requested_start_at),
                path=path,
                available=available,
            )
        )
    return analyze_source_slices(
        sources,
        requested_start_at,
        requested_end_at,
        gap_tolerance_seconds=gap_tolerance_seconds,
    )


def concat_file_line(path: Path) -> str:
    escaped = str(path).replace("'", "'\\''")
    return f"file '{escaped}'"


def write_concat_file(target: Path, paths: Iterable[Path]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(concat_file_line(path) for path in paths) + "\n", encoding="utf-8")


def _trim_args(start_offset_seconds: float, duration_seconds: float) -> list[str]:
    return [
        "-ss",
        f"{max(0.0, start_offset_seconds):.3f}",
        "-t",
        f"{max(0.001, duration_seconds):.3f}",
    ]


def build_fast_group_command(
    concat_path: Path,
    output_path: Path,
    *,
    start_offset_seconds: float,
    duration_seconds: float,
) -> list[str]:
    return [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        *_trim_args(start_offset_seconds, duration_seconds),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]


def build_exact_group_command(
    concat_path: Path,
    output_path: Path,
    *,
    start_offset_seconds: float,
    duration_seconds: float,
) -> list[str]:
    return [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        *_trim_args(start_offset_seconds, duration_seconds),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]


def build_merge_groups_command(concat_path: Path, output_path: Path) -> list[str]:
    return [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]


def create_zip_bundle(output_path: Path, files: Iterable[Path], manifest: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_STORED, allowZip64=True) as archive:
        for path in files:
            archive.write(path, arcname=path.name, compress_type=ZIP_STORED)
        archive.writestr(
            "export-info.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            compress_type=ZIP_STORED,
        )


def export_root() -> Path:
    return settings.data_dir / "exports"


def _safe_under_export_root(path: Path) -> Path:
    root = export_root().resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ExportProcessError("export path escapes export root")
    return resolved


def job_directory(job: ExportJob) -> Path:
    day = job.requested_start_at.strftime("%Y-%m-%d")
    return export_root() / f"camera-{job.camera_id}" / day / f"export-{job.id}"


async def _run_command(command: list[str], partial_path: Path) -> None:
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path.unlink(missing_ok=True)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        partial_path.unlink(missing_ok=True)
        message = (stderr or b"").decode(errors="replace")[-3000:].strip()
        raise ExportProcessError(message or f"FFmpeg exited with status {process.returncode}")
    if not partial_path.is_file() or partial_path.stat().st_size <= 0:
        partial_path.unlink(missing_ok=True)
        raise ExportProcessError("FFmpeg did not create a non-empty export file")


def _artifact_filename(job: ExportJob, start_at: datetime, end_at: datetime, index: int | None = None) -> str:
    stem = f"camera-{job.camera_id}_{start_at:%Y%m%d_%H%M%S}_{end_at:%H%M%S}"
    if index is not None:
        stem += f"_part-{index:02d}"
    return f"{stem}.mp4"


def _manifest(job: ExportJob, analysis: ExportRangeAnalysis, filenames: list[str]) -> dict:
    return {
        "camera_id": job.camera_id,
        "requested_start": analysis.requested_start_at.isoformat(),
        "requested_end": analysis.requested_end_at.isoformat(),
        "requested_duration": analysis.requested_duration,
        "covered_duration": analysis.covered_duration,
        "export_mode": job.export_mode,
        "gap_policy": job.gap_policy,
        "package_mode": job.package_mode,
        "gaps": [
            {
                "start": gap.start_at.isoformat(),
                "end": gap.end_at.isoformat(),
                "duration": gap.duration,
            }
            for gap in analysis.gaps
        ],
        "files": filenames,
    }


class RecordingExportManager:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._queued: set[int] = set()
        self._active_job_id: int | None = None

    def status(self) -> dict:
        return {
            "running": bool(self._task and not self._task.done()),
            "active_job_id": self._active_job_id,
            "queued": self._queue.qsize(),
        }

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        export_root().mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        await self._recover_jobs()
        self._task = asyncio.create_task(self._run(), name="recording-export-manager")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def enqueue(self, job_id: int) -> None:
        if job_id in self._queued or self._active_job_id == job_id:
            return
        self._queued.add(job_id)
        await self._queue.put(job_id)

    async def _recover_jobs(self) -> None:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            await session.execute(
                update(ExportJob)
                .where(ExportJob.status == "processing")
                .values(
                    status="failed",
                    error_message="Export interrupted by service restart",
                    completed_at=now,
                )
            )
            pending = list(
                await session.scalars(
                    select(ExportJob.id).where(ExportJob.status == "pending").order_by(ExportJob.id)
                )
            )
            await session.commit()
        for job_id in pending:
            await self.enqueue(int(job_id))

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = await asyncio.wait_for(self._queue.get(), timeout=60.0)
            except TimeoutError:
                await self.cleanup_expired()
                continue
            self._queued.discard(job_id)
            self._active_job_id = job_id
            try:
                await self.process_job(job_id)
            except Exception:
                logger.exception("recording export job %s failed", job_id)
            finally:
                self._active_job_id = None
                self._queue.task_done()
            await self.cleanup_expired()

    async def _render_group(
        self,
        job: ExportJob,
        group: ExportGroup,
        work_dir: Path,
        index: int,
    ) -> Path:
        sources = sorted(group.sources, key=lambda item: (item.started_at, item.recording_id))
        if not sources:
            raise ExportProcessError("continuous export group has no source recordings")
        concat_path = work_dir / f"group-{index:03d}-sources.txt"
        write_concat_file(concat_path, [item.path for item in sources])
        first_start = sources[0].started_at
        start_offset = max(0.0, (group.start_at - first_start).total_seconds())
        partial = work_dir / f"group-{index:03d}.part.mp4"
        final = work_dir / f"group-{index:03d}.mp4"
        if job.export_mode == "exact":
            command = build_exact_group_command(
                concat_path,
                partial,
                start_offset_seconds=start_offset,
                duration_seconds=group.duration,
            )
        else:
            command = build_fast_group_command(
                concat_path,
                partial,
                start_offset_seconds=start_offset,
                duration_seconds=group.duration,
            )
        await _run_command(command, partial)
        partial.replace(final)
        return final

    async def process_job(self, job_id: int) -> None:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            job = await session.get(ExportJob, job_id)
            if job is None or job.status not in {"pending", "processing"}:
                return
            analysis = await analyze_recording_range(
                session,
                job.camera_id,
                _normalize_db_datetime(job.requested_start_at, now),
                _normalize_db_datetime(job.requested_end_at, now),
            )
            job.status = "processing"
            job.started_at = now
            job.progress = 0.0
            job.gap_count = len(analysis.gaps)
            job.covered_duration = analysis.covered_duration
            await session.commit()

        directory = _safe_under_export_root(job_directory(job))
        work_dir = directory / "work"
        final_dir = directory / "final"
        shutil.rmtree(directory, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        if not analysis.exportable:
            await self._fail_job(job_id, "No locally available recordings cover the requested range")
            shutil.rmtree(directory, ignore_errors=True)
            return

        try:
            group_files: list[Path] = []
            for index, group in enumerate(analysis.groups, start=1):
                group_files.append(await self._render_group(job, group, work_dir, index))
                async with SessionLocal() as session:
                    current = await session.get(ExportJob, job_id)
                    if current is not None:
                        current.progress = min(85.0, (index / len(analysis.groups)) * 80.0)
                        await session.commit()

            artifacts: list[dict] = []
            no_real_gap = len(analysis.gaps) == 0
            effective_policy = "merge" if no_real_gap else job.gap_policy
            effective_package = "individual" if effective_policy == "merge" else job.package_mode

            if effective_policy == "merge":
                filename = _artifact_filename(job, analysis.groups[0].start_at, analysis.groups[-1].end_at)
                final_path = final_dir / filename
                if len(group_files) == 1:
                    group_files[0].replace(final_path)
                else:
                    groups_list = work_dir / "groups.txt"
                    write_concat_file(groups_list, group_files)
                    partial = final_dir / f".{filename}.part.mp4"
                    await _run_command(build_merge_groups_command(groups_list, partial), partial)
                    partial.replace(final_path)
                artifacts.append(
                    {
                        "kind": "mp4",
                        "segment_index": None,
                        "start_at": analysis.groups[0].start_at,
                        "end_at": analysis.groups[-1].end_at,
                        "path": final_path,
                    }
                )
            else:
                split_paths: list[Path] = []
                for index, (group, source_path) in enumerate(
                    zip(analysis.groups, group_files, strict=True), start=1
                ):
                    filename = _artifact_filename(job, group.start_at, group.end_at, index)
                    final_path = final_dir / filename
                    source_path.replace(final_path)
                    split_paths.append(final_path)
                if effective_package == "zip":
                    zip_name = (
                        f"camera-{job.camera_id}_{analysis.requested_start_at:%Y%m%d_%H%M%S}_"
                        f"{analysis.requested_end_at:%H%M%S}.zip"
                    )
                    zip_partial = final_dir / f".{zip_name}.part"
                    zip_final = final_dir / zip_name
                    await asyncio.to_thread(
                        create_zip_bundle,
                        zip_partial,
                        split_paths,
                        _manifest(job, analysis, [path.name for path in split_paths]),
                    )
                    if not zip_partial.is_file() or zip_partial.stat().st_size <= 0:
                        raise ExportProcessError("ZIP bundle was not created")
                    zip_partial.replace(zip_final)
                    for path in split_paths:
                        path.unlink(missing_ok=True)
                    artifacts.append(
                        {
                            "kind": "zip",
                            "segment_index": None,
                            "start_at": analysis.groups[0].start_at,
                            "end_at": analysis.groups[-1].end_at,
                            "path": zip_final,
                        }
                    )
                else:
                    for index, (group, final_path) in enumerate(
                        zip(analysis.groups, split_paths, strict=True), start=1
                    ):
                        artifacts.append(
                            {
                                "kind": "mp4",
                                "segment_index": index,
                                "start_at": group.start_at,
                                "end_at": group.end_at,
                                "path": final_path,
                            }
                        )

            shutil.rmtree(work_dir, ignore_errors=True)
            completed = datetime.now(timezone.utc)
            async with SessionLocal() as session:
                current = await session.get(ExportJob, job_id)
                if current is None:
                    shutil.rmtree(directory, ignore_errors=True)
                    return
                for item in artifacts:
                    path = Path(item["path"])
                    session.add(
                        ExportArtifact(
                            export_job_id=job_id,
                            kind=item["kind"],
                            segment_index=item["segment_index"],
                            start_at=item["start_at"],
                            end_at=item["end_at"],
                            path=str(path),
                            file_size=path.stat().st_size,
                        )
                    )
                current.status = "ready"
                current.progress = 100.0
                current.completed_at = completed
                current.expires_at = completed + EXPORT_TTL
                current.error_message = None
                await session.commit()
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            await self._fail_job(job_id, str(exc)[-3000:])
            raise

    async def _fail_job(self, job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            job = await session.get(ExportJob, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error_message = message[-3000:]
            job.completed_at = datetime.now(timezone.utc)
            job.progress = 0.0
            await session.commit()

    async def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            jobs = list(
                await session.scalars(
                    select(ExportJob).where(
                        ExportJob.status == "ready",
                        ExportJob.expires_at.is_not(None),
                        ExportJob.expires_at <= now,
                    )
                )
            )
            for job in jobs:
                directory = _safe_under_export_root(job_directory(job))
                shutil.rmtree(directory, ignore_errors=True)
                job.status = "expired"
            if jobs:
                await session.commit()


recording_export_manager = RecordingExportManager()
