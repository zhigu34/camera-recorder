import asyncio
import time
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings

_PROXY_CACHE_MAX_AGE_SECONDS = 24 * 3600
_LIVE_START_TIMEOUT_SECONDS = 20.0
_PROXY_PROFILE_VERSION = "web-v3"
MediaSource = Path | str


class PlaybackProxyError(RuntimeError):
    pass


def _source_exists(source: MediaSource) -> bool:
    return not isinstance(source, Path) or source.exists()


async def _capture_ffmpeg_progress(
    reader: asyncio.StreamReader | None,
    on_progress: Callable[[float], None] | None = None,
) -> str:
    """Consume FFmpeg stderr/progress output and keep only a short error tail."""

    if reader is None:
        return ""
    tail = bytearray()
    while True:
        line = await reader.readline()
        if not line:
            break
        text = line.decode(errors="replace").strip()
        handled = False
        if "=" in text:
            key, value = text.split("=", 1)
            if key in {"out_time_us", "out_time_ms"}:
                try:
                    # Despite its historical name, FFmpeg out_time_ms is also
                    # expressed in microseconds.
                    seconds = max(0.0, int(value) / 1_000_000)
                    if on_progress is not None:
                        on_progress(seconds)
                    handled = True
                except ValueError:
                    pass
            elif key in {
                "frame",
                "fps",
                "stream_0_0_q",
                "bitrate",
                "total_size",
                "out_time",
                "dup_frames",
                "drop_frames",
                "speed",
                "progress",
            }:
                handled = True
        if not handled:
            tail.extend(line)
            if len(tail) > 8192:
                del tail[:-8192]
    return tail.decode(errors="replace").strip()


class LiveProxySession:
    def __init__(
        self,
        *,
        manager: "RecordingPlaybackManager",
        recording_id: int,
        process: asyncio.subprocess.Process,
        first_chunk: bytes,
        temp_path: Path,
        temp_file,
        stderr_task: asyncio.Task[str],
        cacheable: bool,
    ) -> None:
        self.manager = manager
        self.recording_id = recording_id
        self.process = process
        self.first_chunk = first_chunk
        self.temp_path = temp_path
        self.temp_file = temp_file
        self.stderr_task = stderr_task
        self.cacheable = cacheable
        self._closed = False

    async def _stop_process(self) -> None:
        if self.process.returncode is not None:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=2.0)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()

    async def _close(self, completed: bool) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._stop_process()
        finally:
            if not self.temp_file.closed:
                self.temp_file.close()
            if not self.stderr_task.done():
                try:
                    await asyncio.wait_for(self.stderr_task, timeout=1.0)
                except TimeoutError:
                    self.stderr_task.cancel()
            if not completed:
                self.temp_path.unlink(missing_ok=True)
            self.manager._live_ids.discard(self.recording_id)
            self.manager._processes.pop(self.recording_id, None)
            self.manager._progress.pop(self.recording_id, None)
            self.manager._cancelled_ids.discard(self.recording_id)
            self.manager._semaphore.release()

    async def stream(self):
        completed = False
        try:
            yield self.first_chunk
            assert self.process.stdout is not None
            while True:
                chunk = await self.process.stdout.read(256 * 1024)
                if not chunk:
                    break
                self.temp_file.write(chunk)
                yield chunk

            returncode = await self.process.wait()
            detail = await self.stderr_task
            if returncode != 0:
                if self.recording_id not in self.manager._cancelled_ids:
                    self.manager._errors[self.recording_id] = (
                        detail or f"ffmpeg exited with code {returncode}"
                    )[-2000:]
                return

            self.temp_file.flush()
            self.temp_file.close()
            if self.cacheable:
                await self.manager._finalize_live_cache(self.recording_id, self.temp_path)
            else:
                # A resumed live proxy starts in the middle of the recording and
                # must never replace the complete compatibility cache.
                self.temp_path.unlink(missing_ok=True)
            self.manager._errors.pop(self.recording_id, None)
            self.manager._set_progress_complete(self.recording_id)
            completed = True
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as exc:
            if self.recording_id not in self.manager._cancelled_ids:
                self.manager._errors[self.recording_id] = str(exc)[-2000:]
        finally:
            await self._close(completed)


class RecordingPlaybackManager:
    def __init__(self) -> None:
        self.proxy_dir = settings.data_dir / "playback-proxies"
        self._tasks: dict[int, asyncio.Task] = {}
        self._errors: dict[int, str] = {}
        self._live_ids: set[int] = set()
        self._processes: dict[int, asyncio.subprocess.Process] = {}
        self._progress: dict[int, dict[str, Any]] = {}
        self._cancelled_ids: set[int] = set()
        self._semaphore = asyncio.Semaphore(1)

    def proxy_path(self, recording_id: int) -> Path:
        return self.proxy_dir / f"{recording_id}.{_PROXY_PROFILE_VERSION}.mp4"

    def live_temp_path(self, recording_id: int) -> Path:
        return self.proxy_dir / f".{recording_id}.{_PROXY_PROFILE_VERSION}.live.part.mp4"

    @staticmethod
    def can_direct_play(video_codec: str | None) -> bool:
        return (video_codec or "").lower() in {"h264", "avc", "avc1"}

    @staticmethod
    def can_try_original(video_codec: str | None) -> bool:
        return (video_codec or "").lower() in {
            "h264",
            "avc",
            "avc1",
            "hevc",
            "h265",
            "hvc1",
            "hev1",
        }

    def _start_progress(
        self,
        recording_id: int,
        duration_seconds: float | None,
        mode: str,
        source_offset_seconds: float = 0.0,
    ) -> None:
        duration = max(0.0, float(duration_seconds or 0))
        source_offset = max(0.0, float(source_offset_seconds or 0))
        if duration > 0:
            source_offset = min(source_offset, duration)
        self._progress[recording_id] = {
            "mode": mode,
            "elapsed_seconds": source_offset,
            "duration_seconds": duration,
            "source_offset_seconds": source_offset,
            "percent": round(source_offset / duration * 100, 1) if duration > 0 else None,
            "started_at_monotonic": time.monotonic(),
            "cancellable": True,
        }

    def _update_progress(self, recording_id: int, elapsed_seconds: float) -> None:
        progress = self._progress.get(recording_id)
        if progress is None:
            return
        source_offset = float(progress.get("source_offset_seconds") or 0)
        absolute_elapsed = source_offset + max(0.0, elapsed_seconds)
        elapsed = max(float(progress.get("elapsed_seconds") or 0), absolute_elapsed)
        duration = float(progress.get("duration_seconds") or 0)
        progress["elapsed_seconds"] = round(elapsed, 3)
        progress["percent"] = (
            round(min(100.0, elapsed / duration * 100), 1) if duration > 0 else None
        )

    def _set_progress_complete(self, recording_id: int) -> None:
        progress = self._progress.get(recording_id)
        if progress is None:
            return
        duration = float(progress.get("duration_seconds") or 0)
        if duration > 0:
            progress["elapsed_seconds"] = duration
            progress["percent"] = 100.0

    def _public_progress(self, recording_id: int) -> dict[str, Any] | None:
        progress = self._progress.get(recording_id)
        if progress is None:
            return None
        return {
            "mode": progress.get("mode"),
            "elapsed_seconds": progress.get("elapsed_seconds", 0.0),
            "duration_seconds": progress.get("duration_seconds", 0.0),
            "source_offset_seconds": progress.get("source_offset_seconds", 0.0),
            "percent": progress.get("percent"),
            "running_seconds": round(
                max(0.0, time.monotonic() - float(progress.get("started_at_monotonic") or 0)),
                1,
            ),
            "cancellable": bool(progress.get("cancellable", True)),
        }

    def status(self, recording_id: int, video_codec: str | None) -> dict[str, Any]:
        progress = self._public_progress(recording_id)
        # Prefer an already-built browser compatibility proxy even when the
        # original H.264 recording would normally be direct-playable. A proxy may
        # have been created after a real browser rejected the original profile,
        # pixel format, audio stream, or container combination.
        proxy = self.proxy_path(recording_id)
        if proxy.exists() and proxy.stat().st_size > 0:
            return {"state": "ready", "direct": False, "error": None, "progress": None}
        if self.can_direct_play(video_codec):
            return {"state": "direct", "direct": True, "error": None, "progress": None}
        if recording_id in self._live_ids:
            return {"state": "streaming", "direct": False, "error": None, "progress": progress}
        task = self._tasks.get(recording_id)
        if task and not task.done():
            return {"state": "generating", "direct": False, "error": None, "progress": progress}
        if recording_id in self._errors:
            return {
                "state": "error",
                "direct": False,
                "error": self._errors[recording_id],
                "progress": None,
            }
        return {"state": "needed", "direct": False, "error": None, "progress": None}

    async def cleanup_cache(self) -> None:
        await asyncio.to_thread(self._cleanup_old_sync)

    def mark_accessed(self, recording_id: int) -> None:
        proxy = self.proxy_path(recording_id)
        if not proxy.exists():
            return
        try:
            proxy.touch()
        except OSError:
            pass

    async def start(
        self,
        recording_id: int,
        source: MediaSource,
        video_codec: str | None,
        audio_codec: str | None = None,
        duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        state = self.status(recording_id, video_codec)
        if state["state"] == "direct":
            if not _source_exists(source):
                raise FileNotFoundError(str(source))
            return state
        if state["state"] in {"ready", "generating", "streaming"}:
            return state
        if not _source_exists(source):
            raise FileNotFoundError(str(source))
        self.proxy_dir.mkdir(parents=True, exist_ok=True)
        await self.cleanup_cache()
        self._errors.pop(recording_id, None)
        self._cancelled_ids.discard(recording_id)
        self._start_progress(recording_id, duration_seconds, "generate")
        task = asyncio.create_task(
            self._generate(recording_id, source, audio_codec),
            name=f"playback-proxy-{recording_id}",
        )
        self._tasks[recording_id] = task
        return self.status(recording_id, video_codec)

    async def open_live_proxy(
        self,
        recording_id: int,
        source: MediaSource,
        audio_codec: str | None,
        duration_seconds: float | None = None,
        start_seconds: float = 0.0,
    ) -> LiveProxySession | None:
        """Start an H.264 fragmented-MP4 proxy from a local path or remote URL."""

        if not _source_exists(source):
            raise FileNotFoundError(str(source))
        target = self.proxy_path(recording_id)
        if target.exists() and target.stat().st_size > 0:
            return None

        source_offset = max(0.0, float(start_seconds or 0))
        duration = max(0.0, float(duration_seconds or 0))
        if duration > 0:
            source_offset = min(source_offset, max(0.0, duration - 0.25))
        cacheable = source_offset <= 0.001

        self.proxy_dir.mkdir(parents=True, exist_ok=True)
        await self.cleanup_cache()
        await self._semaphore.acquire()
        try:
            if target.exists() and target.stat().st_size > 0:
                self._semaphore.release()
                return None

            self._errors.pop(recording_id, None)
            self._cancelled_ids.discard(recording_id)
            self._start_progress(
                recording_id,
                duration_seconds,
                "live",
                source_offset_seconds=source_offset,
            )
            temp = self.live_temp_path(recording_id)
            temp.unlink(missing_ok=True)
            command = self.build_live_proxy_command(
                source,
                audio_codec,
                start_seconds=source_offset,
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._processes[recording_id] = process
            stderr_task = asyncio.create_task(
                _capture_ffmpeg_progress(
                    process.stderr,
                    lambda seconds: self._update_progress(recording_id, seconds),
                )
            )
            assert process.stdout is not None
            try:
                first_chunk = await asyncio.wait_for(
                    process.stdout.read(64 * 1024), timeout=_LIVE_START_TIMEOUT_SECONDS
                )
            except TimeoutError as exc:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
                detail = await stderr_task
                raise PlaybackProxyError(detail or "H.264 边转边播启动超时") from exc

            if not first_chunk:
                returncode = await process.wait()
                detail = await stderr_task
                raise PlaybackProxyError(
                    detail or f"H.264 边转边播启动失败，ffmpeg exit={returncode}"
                )

            temp_file = temp.open("wb")
            temp_file.write(first_chunk)
            self._live_ids.add(recording_id)
            return LiveProxySession(
                manager=self,
                recording_id=recording_id,
                process=process,
                first_chunk=first_chunk,
                temp_path=temp,
                temp_file=temp_file,
                stderr_task=stderr_task,
                cacheable=cacheable,
            )
        except Exception:
            self._processes.pop(recording_id, None)
            self._progress.pop(recording_id, None)
            self._semaphore.release()
            raise

    async def cancel(self, recording_id: int) -> dict[str, Any]:
        """Stop an active playback transcode without touching a completed cache."""

        task = self._tasks.get(recording_id)
        process = self._processes.get(recording_id)
        active = bool((task and not task.done()) or process is not None or recording_id in self._live_ids)
        if not active:
            return {"cancelled": False, "state": "idle"}

        self._cancelled_ids.add(recording_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        process = self._processes.get(recording_id)
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except TimeoutError:
                process.kill()
                await process.wait()

        self._errors.pop(recording_id, None)
        self._progress.pop(recording_id, None)
        self.proxy_dir.mkdir(parents=True, exist_ok=True)
        self.proxy_path(recording_id).with_suffix(".part.mp4").unlink(missing_ok=True)
        self.live_temp_path(recording_id).unlink(missing_ok=True)
        (self.proxy_dir / f".{recording_id}.{_PROXY_PROFILE_VERSION}.cache.part.mp4").unlink(missing_ok=True)
        return {"cancelled": True, "state": "cancelled"}

    def _cleanup_old_sync(self) -> None:
        if not self.proxy_dir.exists():
            return
        cutoff = time.time() - _PROXY_CACHE_MAX_AGE_SECONDS
        for pattern in ("*.mp4", ".*.part.mp4"):
            for path in self.proxy_dir.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue

    @staticmethod
    def _append_audio_options(command: list[str], audio_codec: str | None) -> None:
        # Always normalize compatibility proxies to AAC-LC. Copying camera AAC
        # preserves unknown AAC profiles/sample rates and can still produce a file
        # that plays video but has no audio in Chrome/Firefox/Safari.
        command += [
            "-c:a",
            "aac",
            "-profile:a",
            "aac_low",
            "-b:a",
            "128k",
            "-ar",
            "48000",
        ]

    @staticmethod
    def _append_progress_options(command: list[str]) -> None:
        command += ["-progress", "pipe:2", "-nostats"]

    @classmethod
    def build_proxy_command(
        cls, source: MediaSource, target: Path, audio_codec: str | None
    ) -> list[str]:
        command = [
            settings.ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            "scale='min(1920,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "4",
        ]
        cls._append_audio_options(command, audio_codec)
        cls._append_progress_options(command)
        command += ["-movflags", "+faststart", str(target)]
        return command

    @classmethod
    def build_live_proxy_command(
        cls,
        source: MediaSource,
        audio_codec: str | None,
        start_seconds: float = 0.0,
    ) -> list[str]:
        command = [
            settings.ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        source_offset = max(0.0, float(start_seconds or 0))
        if source_offset > 0.001:
            # Input seeking is accurate when transcoding: FFmpeg seeks near a
            # keyframe, decodes forward and discards frames before this point.
            command += ["-ss", f"{source_offset:.3f}"]
        command += [
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            "scale='min(1920,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "4",
            "-force_key_frames",
            "expr:gte(t,n_forced*2)",
        ]
        cls._append_audio_options(command, audio_codec)
        cls._append_progress_options(command)
        command += [
            "-movflags",
            "+frag_keyframe+empty_moov+default_base_moof",
            "-flush_packets",
            "1",
            "-f",
            "mp4",
            "pipe:1",
        ]
        return command

    async def _finalize_live_cache(self, recording_id: int, live_temp: Path) -> None:
        target = self.proxy_path(recording_id)
        cache_temp = self.proxy_dir / f".{recording_id}.{_PROXY_PROFILE_VERSION}.cache.part.mp4"
        cache_temp.unlink(missing_ok=True)
        command = [
            settings.ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(live_temp),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(cache_temp),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode == 0 and cache_temp.exists() and cache_temp.stat().st_size > 0:
                cache_temp.replace(target)
                live_temp.unlink(missing_ok=True)
                return
            cache_temp.unlink(missing_ok=True)
            if live_temp.exists() and live_temp.stat().st_size > 0:
                live_temp.replace(target)
                return
            detail = stderr.decode(errors="replace")[-2000:].strip()
            raise PlaybackProxyError(detail or "H.264 Proxy 缓存整理失败")
        except Exception:
            cache_temp.unlink(missing_ok=True)
            if live_temp.exists() and live_temp.stat().st_size > 0:
                live_temp.replace(target)
                return
            raise

    async def _generate(
        self,
        recording_id: int,
        source: MediaSource,
        audio_codec: str | None,
    ) -> None:
        process: asyncio.subprocess.Process | None = None
        async with self._semaphore:
            target = self.proxy_path(recording_id)
            temp = target.with_suffix(".part.mp4")
            try:
                temp.unlink(missing_ok=True)
                command = self.build_proxy_command(source, temp, audio_codec)
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                self._processes[recording_id] = process
                stderr_task = asyncio.create_task(
                    _capture_ffmpeg_progress(
                        process.stderr,
                        lambda seconds: self._update_progress(recording_id, seconds),
                    )
                )
                returncode = await process.wait()
                detail = await stderr_task
                if returncode != 0:
                    if recording_id in self._cancelled_ids:
                        return
                    raise RuntimeError(detail or f"ffmpeg exited with code {returncode}")
                if not temp.exists() or temp.stat().st_size <= 0:
                    raise RuntimeError("playback proxy was not created")
                temp.replace(target)
                self._set_progress_complete(recording_id)
                self._errors.pop(recording_id, None)
            except asyncio.CancelledError:
                if process is not None and process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                temp.unlink(missing_ok=True)
                raise
            except Exception as exc:
                temp.unlink(missing_ok=True)
                if recording_id not in self._cancelled_ids:
                    self._errors[recording_id] = str(exc)[-2000:]
            finally:
                self._tasks.pop(recording_id, None)
                self._processes.pop(recording_id, None)
                self._progress.pop(recording_id, None)
                self._cancelled_ids.discard(recording_id)


recording_playback_manager = RecordingPlaybackManager()
