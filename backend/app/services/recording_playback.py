import asyncio
import time
from pathlib import Path
from typing import Any

from app.core.config import settings

_PROXY_CACHE_MAX_AGE_SECONDS = 24 * 3600
_LIVE_START_TIMEOUT_SECONDS = 20.0


class PlaybackProxyError(RuntimeError):
    pass


async def _capture_stderr(reader: asyncio.StreamReader | None) -> str:
    if reader is None:
        return ""
    tail = bytearray()
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            break
        tail.extend(chunk)
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
    ) -> None:
        self.manager = manager
        self.recording_id = recording_id
        self.process = process
        self.first_chunk = first_chunk
        self.temp_path = temp_path
        self.temp_file = temp_file
        self.stderr_task = stderr_task
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
                self.manager._errors[self.recording_id] = (
                    detail or f"ffmpeg exited with code {returncode}"
                )[-2000:]
                return

            self.temp_file.flush()
            self.temp_file.close()
            await self.manager._finalize_live_cache(self.recording_id, self.temp_path)
            self.manager._errors.pop(self.recording_id, None)
            completed = True
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as exc:
            self.manager._errors[self.recording_id] = str(exc)[-2000:]
        finally:
            await self._close(completed)


class RecordingPlaybackManager:
    def __init__(self) -> None:
        self.proxy_dir = settings.data_dir / "playback-proxies"
        self._tasks: dict[int, asyncio.Task] = {}
        self._errors: dict[int, str] = {}
        self._live_ids: set[int] = set()
        # Playback transcoding is deliberately conservative so a user opening a
        # recording cannot steal CPU from the primary multi-camera recording path.
        self._semaphore = asyncio.Semaphore(1)

    def proxy_path(self, recording_id: int) -> Path:
        return self.proxy_dir / f"{recording_id}.mp4"

    def live_temp_path(self, recording_id: int) -> Path:
        return self.proxy_dir / f".{recording_id}.live.part.mp4"

    @staticmethod
    def can_direct_play(video_codec: str | None) -> bool:
        """Return codecs that are safe to direct-play without client probing.

        HEVC is intentionally not included here. Some browsers/platforms can play
        hvc1/hev1 natively and the frontend will try the original file first, but
        support is client-dependent. This method remains the guaranteed fallback
        policy used by the API's `source=auto` mode.
        """

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

    def status(self, recording_id: int, video_codec: str | None) -> dict[str, Any]:
        if self.can_direct_play(video_codec):
            return {"state": "direct", "direct": True, "error": None}
        proxy = self.proxy_path(recording_id)
        if proxy.exists() and proxy.stat().st_size > 0:
            return {"state": "ready", "direct": False, "error": None}
        if recording_id in self._live_ids:
            return {"state": "streaming", "direct": False, "error": None}
        task = self._tasks.get(recording_id)
        if task and not task.done():
            return {"state": "generating", "direct": False, "error": None}
        if recording_id in self._errors:
            return {"state": "error", "direct": False, "error": self._errors[recording_id]}
        return {"state": "needed", "direct": False, "error": None}

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
        source: Path,
        video_codec: str | None,
        audio_codec: str | None = None,
    ) -> dict[str, Any]:
        state = self.status(recording_id, video_codec)
        if state["state"] == "direct":
            if not source.exists():
                raise FileNotFoundError(str(source))
            return state
        if state["state"] in {"ready", "generating", "streaming"}:
            return state
        if not source.exists():
            raise FileNotFoundError(str(source))
        self.proxy_dir.mkdir(parents=True, exist_ok=True)
        await self.cleanup_cache()
        self._errors.pop(recording_id, None)
        task = asyncio.create_task(
            self._generate(recording_id, source, audio_codec),
            name=f"playback-proxy-{recording_id}",
        )
        self._tasks[recording_id] = task
        return {"state": "generating", "direct": False, "error": None}

    async def open_live_proxy(
        self,
        recording_id: int,
        source: Path,
        audio_codec: str | None,
    ) -> LiveProxySession | None:
        """Start a fragmented-MP4 H.264 proxy that can be played immediately.

        The same bytes are saved to a temporary fMP4 file. When transcoding
        completes, that file is remuxed with stream-copy into the normal faststart
        proxy cache so later playback keeps normal HTTP Range seeking.
        """

        if not source.exists():
            raise FileNotFoundError(str(source))
        target = self.proxy_path(recording_id)
        if target.exists() and target.stat().st_size > 0:
            return None

        self.proxy_dir.mkdir(parents=True, exist_ok=True)
        await self.cleanup_cache()
        await self._semaphore.acquire()
        try:
            # A queued request may have waited for another proxy generation to
            # finish. Re-check the cache before spending CPU on duplicate work.
            if target.exists() and target.stat().st_size > 0:
                self._semaphore.release()
                return None

            self._errors.pop(recording_id, None)
            temp = self.live_temp_path(recording_id)
            temp.unlink(missing_ok=True)
            command = self.build_live_proxy_command(source, audio_codec)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stderr_task = asyncio.create_task(_capture_stderr(process.stderr))
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
            )
        except Exception:
            self._semaphore.release()
            raise

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
        # Camera recordings are normally AAC already. Copying compatible audio
        # avoids wasting CPU and preserves the original audio quality. Unknown or
        # incompatible audio is converted to AAC for broad browser compatibility.
        if (audio_codec or "").lower() == "aac":
            command += ["-c:a", "copy"]
        else:
            command += ["-c:a", "aac", "-b:a", "96k"]

    @classmethod
    def build_proxy_command(
        cls, source: Path, target: Path, audio_codec: str | None
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
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "2",
        ]
        cls._append_audio_options(command, audio_codec)
        command += ["-movflags", "+faststart", str(target)]
        return command

    @classmethod
    def build_live_proxy_command(cls, source: Path, audio_codec: str | None) -> list[str]:
        command = [
            settings.ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-crf",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "2",
            "-force_key_frames",
            "expr:gte(t,n_forced*2)",
        ]
        cls._append_audio_options(command, audio_codec)
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
        cache_temp = self.proxy_dir / f".{recording_id}.cache.part.mp4"
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
            # The completed fMP4 itself remains a valid fallback cache even if the
            # cheap stream-copy normalization unexpectedly fails.
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
        source: Path,
        audio_codec: str | None,
    ) -> None:
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
                _, stderr = await process.communicate()
                if process.returncode != 0:
                    detail = stderr.decode(errors="replace")[-2000:].strip()
                    raise RuntimeError(detail or f"ffmpeg exited with code {process.returncode}")
                if not temp.exists() or temp.stat().st_size <= 0:
                    raise RuntimeError("playback proxy was not created")
                temp.replace(target)
                self._errors.pop(recording_id, None)
            except Exception as exc:
                temp.unlink(missing_ok=True)
                self._errors[recording_id] = str(exc)[-2000:]
            finally:
                self._tasks.pop(recording_id, None)


recording_playback_manager = RecordingPlaybackManager()
