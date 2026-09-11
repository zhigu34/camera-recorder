import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx
from sqlalchemy import or_, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.recording import Recording
from app.models.upload import UploadTask
from app.services.event_log import add_event
from app.services.system_settings import RuntimeSettings, load_runtime_settings


class WebDAVError(RuntimeError):
    pass


class OpenListWebDAVProvider:
    def __init__(self, runtime: RuntimeSettings) -> None:
        self.base_url = runtime.webdav_url.rstrip("/")
        self.username = runtime.webdav_username
        self.password = runtime.webdav_password

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def _url(self, relative_path: str = "") -> str:
        segments = [quote(segment, safe="") for segment in PurePosixPath(relative_path).parts if segment not in ("/", ".")]
        if not segments:
            return self.base_url + "/"
        return self.base_url + "/" + "/".join(segments)

    async def _mkdirs(self, client: httpx.AsyncClient, directory: str) -> None:
        current: list[str] = []
        for part in PurePosixPath(directory).parts:
            if part in ("/", ".", ""):
                continue
            current.append(part)
            response = await client.request("MKCOL", self._url("/".join(current)))
            if response.status_code not in (200, 201, 204, 301, 302, 405):
                raise WebDAVError(
                    f"MKCOL {'/'.join(current)} failed: HTTP {response.status_code} {response.text[:300]}"
                )

    async def upload(self, source: Path, remote_path: str) -> None:
        if not self.configured:
            raise WebDAVError("OpenList WebDAV credentials are not configured")
        if not source.exists():
            raise WebDAVError(f"local file not found: {source}")

        auth = httpx.BasicAuth(self.username, self.password)
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=30.0)
        async with httpx.AsyncClient(auth=auth, timeout=timeout, follow_redirects=True) as client:
            parent = str(PurePosixPath(remote_path).parent)
            if parent not in (".", ""):
                await self._mkdirs(client, parent)

            file_size = source.stat().st_size

            async def chunks():
                with source.open("rb") as handle:
                    while True:
                        block = await asyncio.to_thread(handle.read, 4 * 1024 * 1024)
                        if not block:
                            break
                        yield block

            response = await client.put(
                self._url(remote_path),
                content=chunks(),
                headers={"Content-Length": str(file_size), "Content-Type": "application/octet-stream"},
            )
            if response.status_code not in (200, 201, 204):
                raise WebDAVError(
                    f"PUT {remote_path} failed: HTTP {response.status_code} {response.text[:500]}"
                )

            verify = await client.head(self._url(remote_path))
            if verify.status_code not in (200, 204):
                raise WebDAVError(f"HEAD verify failed: HTTP {verify.status_code}")
            remote_size = verify.headers.get("content-length")
            if remote_size and int(remote_size) != file_size:
                raise WebDAVError(
                    f"uploaded size mismatch: local={file_size}, remote={remote_size}"
                )


class UploadManager:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def runtime(self) -> RuntimeSettings:
        async with SessionLocal() as session:
            return await load_runtime_settings(session)

    async def status(self) -> dict:
        runtime = await self.runtime()
        provider = OpenListWebDAVProvider(runtime)
        return {
            "enabled": runtime.upload_enabled,
            "configured": provider.configured,
            "active": runtime.upload_enabled and provider.configured,
            "provider": "openlist_webdav",
            "webdav_url": runtime.webdav_url,
            "webdav_root": runtime.webdav_root,
            "local_retention_hours": runtime.local_retention_hours,
        }

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="upload-manager")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except TimeoutError:
                self._task.cancel()

    async def _run(self) -> None:
        while not self._stop.is_set():
            runtime = await self.runtime()
            provider = OpenListWebDAVProvider(runtime)
            if runtime.upload_enabled and provider.configured:
                await self.scan_once(runtime)
                await self.cleanup_uploaded_files(runtime)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=settings.upload_scan_interval_seconds
                )
            except TimeoutError:
                pass

    def remote_path_for(self, recording: Recording, runtime: RuntimeSettings) -> str:
        source = Path(recording.mp4_path)
        try:
            relative = source.relative_to(settings.recordings_dir)
        except ValueError:
            relative = Path(source.name)
        root = runtime.webdav_root.strip("/")
        parts = [root] if root else []
        parts.extend(relative.parts)
        return PurePosixPath(*parts).as_posix()

    async def scan_once(self, runtime: RuntimeSettings | None = None) -> None:
        runtime = runtime or await self.runtime()
        provider = OpenListWebDAVProvider(runtime)
        if not runtime.upload_enabled or not provider.configured:
            return
        await self._ensure_tasks(runtime)
        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            task_ids = list(
                await session.scalars(
                    select(UploadTask.id)
                    .where(
                        UploadTask.status.in_(("pending", "retry_wait")),
                        UploadTask.retry_count < runtime.upload_retry_max,
                        or_(UploadTask.next_retry_at.is_(None), UploadTask.next_retry_at <= now),
                    )
                    .order_by(UploadTask.id)
                    .limit(max(1, runtime.upload_concurrency) * 2)
                )
            )
        if task_ids:
            semaphore = asyncio.Semaphore(max(1, runtime.upload_concurrency))
            await asyncio.gather(
                *(self._process_guarded(task_id, runtime, provider, semaphore) for task_id in task_ids)
            )

    async def _ensure_tasks(self, runtime: RuntimeSettings) -> None:
        async with SessionLocal() as session:
            recordings = list(
                await session.scalars(
                    select(Recording)
                    .where(
                        Recording.status == "ready",
                        Recording.upload_status.in_(("pending", "failed", "retry_wait")),
                    )
                    .order_by(Recording.id)
                    .limit(500)
                )
            )
            if not recordings:
                return
            recording_ids = [recording.id for recording in recordings]
            existing_ids = set(
                await session.scalars(
                    select(UploadTask.recording_id).where(
                        UploadTask.recording_id.in_(recording_ids)
                    )
                )
            )
            for recording in recordings:
                if recording.id in existing_ids:
                    continue
                session.add(
                    UploadTask(
                        recording_id=recording.id,
                        remote_path=self.remote_path_for(recording, runtime),
                        status="pending",
                    )
                )
            await session.commit()

    async def _process_guarded(
        self,
        task_id: int,
        runtime: RuntimeSettings,
        provider: OpenListWebDAVProvider,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            await self.process_task(task_id, runtime, provider)

    async def process_task(
        self,
        task_id: int,
        runtime: RuntimeSettings | None = None,
        provider: OpenListWebDAVProvider | None = None,
    ) -> None:
        runtime = runtime or await self.runtime()
        provider = provider or OpenListWebDAVProvider(runtime)
        async with SessionLocal() as session:
            task = await session.get(UploadTask, task_id)
            if task is None:
                return
            recording = await session.get(Recording, task.recording_id)
            if recording is None:
                task.status = "failed"
                task.last_error = "recording no longer exists"
                await session.commit()
                return

            source = Path(recording.mp4_path)
            if not source.exists():
                task.status = "failed"
                task.last_error = "local MP4 does not exist"
                recording.upload_status = "failed"
                await session.commit()
                return

            task.status = "uploading"
            task.started_at = datetime.now(timezone.utc)
            task.last_error = None
            recording.upload_status = "uploading"
            await session.commit()
            remote_path = task.remote_path

        try:
            await provider.upload(source, remote_path)
        except Exception as exc:
            async with SessionLocal() as session:
                task = await session.get(UploadTask, task_id)
                recording = await session.get(Recording, task.recording_id) if task else None
                if task is None:
                    return
                task.retry_count += 1
                task.last_error = str(exc)[-2000:]
                if task.retry_count >= runtime.upload_retry_max:
                    task.status = "failed"
                    task.next_retry_at = None
                    if recording:
                        recording.upload_status = "failed"
                else:
                    delay = min(60 * (2 ** max(0, task.retry_count - 1)), 3600)
                    task.status = "retry_wait"
                    task.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    if recording:
                        recording.upload_status = "retry_wait"
                await session.commit()
            return

        async with SessionLocal() as session:
            task = await session.get(UploadTask, task_id)
            recording = await session.get(Recording, task.recording_id) if task else None
            if task is None:
                return
            task.status = "success"
            task.completed_at = datetime.now(timezone.utc)
            task.next_retry_at = None
            task.last_error = None
            if recording:
                recording.upload_status = "success"
            await session.commit()

    async def retry(self, task_id: int) -> bool:
        async with SessionLocal() as session:
            task = await session.get(UploadTask, task_id)
            if task is None:
                return False
            task.status = "pending"
            task.retry_count = 0
            task.next_retry_at = None
            task.last_error = None
            recording = await session.get(Recording, task.recording_id)
            if recording:
                recording.upload_status = "pending"
            await session.commit()
        return True

    async def cleanup_uploaded_files(self, runtime: RuntimeSettings | None = None) -> int:
        runtime = runtime or await self.runtime()
        if runtime.local_retention_hours < 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=runtime.local_retention_hours)
        async with SessionLocal() as session:
            recordings = list(
                await session.scalars(
                    select(Recording).where(
                        Recording.status == "ready",
                        Recording.upload_status == "success",
                        Recording.ended_at.is_not(None),
                        Recording.ended_at <= cutoff,
                    )
                )
            )
            deleted = 0
            freed_bytes = 0
            for recording in recordings:
                path = Path(recording.mp4_path)
                file_size = int(recording.file_size or 0)
                if path.exists():
                    try:
                        if not file_size:
                            file_size = path.stat().st_size
                        await asyncio.to_thread(path.unlink)
                    except OSError:
                        continue
                recording.status = "deleted"
                deleted += 1
                freed_bytes += max(0, file_size)
            if deleted:
                add_event(
                    session,
                    level="info",
                    category="storage",
                    code="storage.retention_cleanup_completed",
                    message=f"本地保留期清理完成：删除 {deleted} 个已上传录像",
                    metadata={
                        "deleted_files": deleted,
                        "freed_bytes": freed_bytes,
                        "local_retention_hours": runtime.local_retention_hours,
                    },
                )
                await session.commit()
            return deleted


upload_manager = UploadManager()
