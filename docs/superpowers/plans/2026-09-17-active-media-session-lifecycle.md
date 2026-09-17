# Active Media Session Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make detail previews, preview-wall slots, and HIK bridge streams camera-scoped runtime resources that terminate immediately on camera disable, reload, deletion, or adapter switch, without being recreated by runtime restore.

**Architecture:** Add a process-local `CameraMediaSessionRegistry` that stores camera-scoped async close callbacks and detaches them atomically before cleanup. Detail preview, preview-wall slot, and HIK internal-media lifetimes register with this registry; `CameraRuntimeCoordinator.stop_all()` invokes media teardown before motion/event/recorder/schedule teardown, while `restore()` remains preview-agnostic.

**Tech Stack:** FastAPI, asyncio, SQLAlchemy async ORM, FFmpeg subprocesses, httpx, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-17-active-media-session-lifecycle-design.md`

## Global Constraints

- Use approved option A: disable, reload, deletion, and adapter switch immediately terminate active preview/media sessions; users reopen previews explicitly.
- Media-session cleanup is best-effort and must not block camera configuration persistence or lifecycle teardown.
- `CameraRuntimeCoordinator.restore()` must never recreate preview/media sessions.
- Target adapter validation/probing must remain before camera runtime teardown.
- The registry is process-local only; do not add SQLite persistence or a HIK bridge-wide dashboard/session inventory.
- Do not redesign recorder/schedule/motion/event ownership.
- Preserve existing detail-preview auto sub-to-main fallback, preview-wall per-slot fallback/error behavior, HIK empty-chunk filtering, and best-effort HIK cleanup.
- No frontend auto-reconnect work in this slice.

---

## File Structure

- Create `backend/app/services/camera_media_session_registry.py`: generic camera-scoped async session membership/teardown.
- Modify `backend/app/services/camera_preview.py`: make detail-preview session close public and idempotent.
- Modify `backend/app/api/cameras.py`: register detail preview after a successful open and unregister on stream completion.
- Modify `backend/app/services/preview_wall.py`: introduce a slot session object that owns one FFmpeg process and exposes `stream()` + `close()`.
- Modify `backend/app/api/preview_wall.py`: register each slot by `camera_id` and unregister independently.
- Modify `backend/app/api/hik_media.py`: register HIK bridge `stream_id` after creation and unregister in iterator finalization.
- Modify `backend/app/services/hik_media_proxy.py`: preserve iterator semantics while making natural and external close share one idempotent closer.
- Modify `backend/app/services/camera_runtime_coordinator.py`: call media-session teardown first in `stop_all()` only.
- Modify `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`: mark active preview/session termination and HIK temporary-session release complete only after final CI is green.

---

### Task 1: CameraMediaSessionRegistry

**Files:**
- Create: `backend/app/services/camera_media_session_registry.py`
- Create: `backend/tests/test_camera_media_session_registry.py`

**Interfaces:**
- Produces: `SessionCloser = Callable[[], Awaitable[None]]`
- Produces: `CameraMediaSessionRegistry.register(camera_id: int, closer: SessionCloser) -> str`
- Produces: `CameraMediaSessionRegistry.unregister(camera_id: int, session_id: str) -> None`
- Produces: `CameraMediaSessionRegistry.active_count(camera_id: int) -> int`
- Produces: `CameraMediaSessionRegistry.stop_camera(camera_id: int) -> None`
- Produces: `CameraMediaSessionRegistry.stop_all() -> None`
- Produces singleton: `camera_media_session_registry`

- [ ] **Step 1: Write failing registry tests**

```python
import asyncio

import pytest

from app.services.camera_media_session_registry import CameraMediaSessionRegistry


@pytest.mark.asyncio
async def test_stop_camera_closes_only_target_camera_sessions() -> None:
    registry = CameraMediaSessionRegistry()
    calls: list[str] = []

    async def close_a1() -> None:
        calls.append("a1")

    async def close_a2() -> None:
        calls.append("a2")

    async def close_b1() -> None:
        calls.append("b1")

    await registry.register(1, close_a1)
    await registry.register(1, close_a2)
    await registry.register(2, close_b1)

    await registry.stop_camera(1)

    assert calls == ["a1", "a2"]
    assert await registry.active_count(1) == 0
    assert await registry.active_count(2) == 1


@pytest.mark.asyncio
async def test_stop_camera_detaches_before_awaiting_closers() -> None:
    registry = CameraMediaSessionRegistry()
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    calls: list[str] = []

    async def old_close() -> None:
        close_started.set()
        await allow_close.wait()
        calls.append("old")

    await registry.register(7, old_close)
    stopping = asyncio.create_task(registry.stop_camera(7))
    await close_started.wait()

    async def new_close() -> None:
        calls.append("new")

    await registry.register(7, new_close)
    allow_close.set()
    await stopping

    assert calls == ["old"]
    assert await registry.active_count(7) == 1


@pytest.mark.asyncio
async def test_unregister_is_idempotent() -> None:
    registry = CameraMediaSessionRegistry()

    async def closer() -> None:
        return None

    session_id = await registry.register(3, closer)
    await registry.unregister(3, session_id)
    await registry.unregister(3, session_id)

    assert await registry.active_count(3) == 0


@pytest.mark.asyncio
async def test_closer_failure_does_not_block_remaining_sessions() -> None:
    registry = CameraMediaSessionRegistry()
    calls: list[str] = []

    async def failing() -> None:
        calls.append("failing")
        raise RuntimeError("cleanup failed")

    async def succeeding() -> None:
        calls.append("succeeding")

    await registry.register(9, failing)
    await registry.register(9, succeeding)
    await registry.stop_camera(9)

    assert calls == ["failing", "succeeding"]
    assert await registry.active_count(9) == 0
```

Add one more test proving `stop_all()` drains sessions from multiple cameras.

- [ ] **Step 2: Run the new test file and confirm RED**

From `backend/`:

```bash
uv run pytest tests/test_camera_media_session_registry.py -q
```

Expected: import/collection failure because the registry module does not yet exist.

- [ ] **Step 3: Implement the minimal registry**

```python
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

SessionCloser = Callable[[], Awaitable[None]]
logger = logging.getLogger(__name__)


class CameraMediaSessionRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[int, dict[str, SessionCloser]] = {}

    async def register(self, camera_id: int, closer: SessionCloser) -> str:
        session_id = uuid4().hex
        async with self._lock:
            self._sessions.setdefault(camera_id, {})[session_id] = closer
        return session_id

    async def unregister(self, camera_id: int, session_id: str) -> None:
        async with self._lock:
            sessions = self._sessions.get(camera_id)
            if not sessions:
                return
            sessions.pop(session_id, None)
            if not sessions:
                self._sessions.pop(camera_id, None)

    async def active_count(self, camera_id: int) -> int:
        async with self._lock:
            return len(self._sessions.get(camera_id, {}))

    async def _close_detached(
        self,
        camera_id: int,
        sessions: dict[str, SessionCloser],
    ) -> None:
        for session_id, closer in sessions.items():
            try:
                await closer()
            except Exception:
                logger.exception(
                    "failed to close camera media session",
                    extra={"camera_id": camera_id, "session_id": session_id},
                )

    async def stop_camera(self, camera_id: int) -> None:
        async with self._lock:
            sessions = self._sessions.pop(camera_id, {})
        await self._close_detached(camera_id, sessions)

    async def stop_all(self) -> None:
        async with self._lock:
            detached = self._sessions
            self._sessions = {}
        for camera_id, sessions in detached.items():
            await self._close_detached(camera_id, sessions)


camera_media_session_registry = CameraMediaSessionRegistry()
```

- [ ] **Step 4: Run tests and quality checks**

```bash
uv run pytest tests/test_camera_media_session_registry.py -q
uv run ruff check app/services/camera_media_session_registry.py tests/test_camera_media_session_registry.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/app/services/camera_media_session_registry.py backend/tests/test_camera_media_session_registry.py
git commit -m "feat: add camera media session registry"
```

---

### Task 2: Detail MJPEG preview lifecycle

**Files:**
- Modify: `backend/app/services/camera_preview.py`
- Modify: `backend/app/api/cameras.py`
- Create: `backend/tests/test_camera_preview_session_lifecycle.py`
- Preserve: `backend/tests/test_camera_preview.py`

**Interfaces:**
- Consumes: `camera_media_session_registry.register/unregister`
- Produces: `PreviewSession.close() -> Awaitable[None]`, idempotent
- Endpoint response iterator always unregisters in `finally`

- [ ] **Step 1: Write failing idempotent close tests**

Use a fake subprocess whose `returncode` starts as `None`, `terminate()` records calls and flips `returncode`, and `wait()` is async.

```python
@pytest.mark.asyncio
async def test_preview_session_close_is_idempotent() -> None:
    process = FakeProcess()
    session = PreviewSession(process=process, first_chunk=b"frame")

    await session.close()
    await session.close()

    assert process.terminate_calls == 1
```

Also consume `session.stream()` after an external `close()` and assert no second terminate occurs.

- [ ] **Step 2: Write failing endpoint registration/unregister test**

Patch `app.api.cameras.open_mjpeg_preview` to return a fake session and patch the imported registry singleton with a fake registry that records `register()` and `unregister()`. Call the existing `preview_camera()` path through the project FastAPI test client, consume the stream body, then assert:

```python
assert registry.registered_camera_ids == [camera_id]
assert registry.unregistered == [(camera_id, "session-1")]
```

Keep the existing `X-Preview-Stream` assertion so the lifecycle wrapper cannot drop headers.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run pytest tests/test_camera_preview_session_lifecycle.py -q
```

Expected: failure because `PreviewSession.close()` and endpoint registry integration do not exist.

- [ ] **Step 4: Implement idempotent PreviewSession.close()**

Modify imports:

```python
from dataclasses import dataclass, field
```

Modify the session:

```python
@dataclass(slots=True)
class PreviewSession:
    process: asyncio.subprocess.Process
    first_chunk: bytes
    _closed: bool = False
    _close_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            await _stop_process(self.process)

    async def stream(self) -> AsyncIterator[bytes]:
        try:
            if self.first_chunk:
                yield self.first_chunk
            assert self.process.stdout is not None
            while True:
                chunk = await self.process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            await self.close()
```

- [ ] **Step 5: Register detail preview in `preview_camera()`**

Import the registry singleton in `app.api.cameras`, then after the final preview session has been selected/opened:

```python
session_id = await camera_media_session_registry.register(camera_id, session.close)

async def registered_stream():
    try:
        async for chunk in session.stream():
            yield chunk
    finally:
        await camera_media_session_registry.unregister(camera_id, session_id)
```

Return `StreamingResponse(registered_stream(), ...)` with the existing media type and headers unchanged.

- [ ] **Step 6: Run focused and existing preview tests**

```bash
uv run pytest tests/test_camera_preview_session_lifecycle.py tests/test_camera_preview.py -q
uv run ruff check app/services/camera_preview.py app/api/cameras.py tests/test_camera_preview_session_lifecycle.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add backend/app/services/camera_preview.py backend/app/api/cameras.py backend/tests/test_camera_preview_session_lifecycle.py
git commit -m "feat: track active camera detail previews"
```

---

### Task 3: Preview-wall per-slot lifecycle

**Files:**
- Modify: `backend/app/services/preview_wall.py`
- Modify: `backend/app/api/preview_wall.py`
- Create: `backend/tests/test_preview_wall_session_lifecycle.py`
- Preserve: `backend/tests/test_preview_wall.py`

**Interfaces:**
- Consumes: `camera_media_session_registry.register/unregister`
- Produces: `WallPreviewSession(source: WallPreviewSource)`
- Produces: `WallPreviewSession.stream(on_frame: FrameCallback) -> Awaitable[None]`
- Produces: `WallPreviewSession.close() -> Awaitable[None]`, idempotent

- [ ] **Step 1: Write failing WallPreviewSession close test**

Create a fake process whose stdout blocks on an event until externally closed. Spawn `session.stream(on_frame)` as a task, wait until the fake process starts, call `session.close()`, release the fake read, await the task, and assert exactly one terminate.

```python
@pytest.mark.asyncio
async def test_wall_preview_session_external_close_is_idempotent(monkeypatch) -> None:
    source = WallPreviewSource(
        ip="192.0.2.10",
        port=554,
        username="user",
        password="pass",
        rtsp_path="/sub",
        rtsp_timeout_us=5_000_000,
        fps=3,
        width=480,
    )
    process = FakeProcess()

    async def fake_spawn(*args, **kwargs):
        process.started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    session = WallPreviewSession(source)

    async def on_frame(frame: bytes) -> None:
        return None

    streaming = asyncio.create_task(session.stream(on_frame))
    await process.started.wait()
    await session.close()
    await session.close()
    process.release_read.set()
    await streaming

    assert process.terminate_calls == 1
```

- [ ] **Step 2: Write failing per-camera slot isolation test**

Use two `WallPreviewSession` fakes registered under cameras 10 and 11. Invoke registry `stop_camera(10)` and assert session 10 is closed, session 11 is not closed, and the fake WebSocket close method was never called.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run pytest tests/test_preview_wall_session_lifecycle.py -q
```

Expected: failure because `WallPreviewSession` does not exist and API slots are not registry-owned.

- [ ] **Step 4: Extract process opening into `_open_wall_process()`**

```python
async def _open_wall_process(source: WallPreviewSource) -> asyncio.subprocess.Process:
    command = build_wall_preview_command(
        ip=source.ip,
        port=source.port,
        username=source.username,
        password=source.password,
        rtsp_path=source.rtsp_path,
        rtsp_timeout_us=source.rtsp_timeout_us,
        fps=source.fps,
        width=source.width,
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found") from exc
    assert process.stdout is not None
    return process
```

- [ ] **Step 5: Implement `WallPreviewSession` with the existing read/parser loop**

```python
class WallPreviewSession:
    def __init__(self, source: WallPreviewSource) -> None:
        self.source = source
        self._process: asyncio.subprocess.Process | None = None
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if self._process is not None:
                await _stop_process(self._process)

    async def stream(self, on_frame: FrameCallback) -> None:
        if self._closed:
            return
        process = await _open_wall_process(self.source)
        self._process = process
        assert process.stdout is not None
        parser = JpegFrameParser()
        read_timeout = max(8.0, self.source.rtsp_timeout_us / 1_000_000 + 3.0)
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        process.stdout.read(64 * 1024),
                        timeout=read_timeout,
                    )
                except TimeoutError as exc:
                    raise RuntimeError("实时预览连接超时") from exc
                if not chunk:
                    if process.returncode is None:
                        await process.wait()
                    raise RuntimeError("实时预览码流已结束")
                for frame in parser.feed(chunk):
                    await on_frame(frame)
                    read_timeout = 30.0
        finally:
            await self.close()


async def stream_preview_frames(source: WallPreviewSource, on_frame: FrameCallback) -> None:
    await WallPreviewSession(source).stream(on_frame)
```

- [ ] **Step 6: Wire primary/fallback slot sessions through the registry**

In `app.api.preview_wall`, change the slot streamer to create a `WallPreviewSession` for each active source. Use a helper that registers before streaming and unregisters in `finally`:

```python
async def run_registered_session(
    camera_id: int,
    session: WallPreviewSession,
    on_frame,
) -> None:
    session_id = await camera_media_session_registry.register(camera_id, session.close)
    try:
        await session.stream(on_frame)
    finally:
        await camera_media_session_registry.unregister(camera_id, session_id)
```

Call it for primary; if primary fails and fallback is allowed, create a fresh fallback session and call the same helper. Do not close the WebSocket from registry teardown.

- [ ] **Step 7: Run focused + existing wall tests**

```bash
uv run pytest tests/test_preview_wall_session_lifecycle.py tests/test_preview_wall.py -q
uv run ruff check app/services/preview_wall.py app/api/preview_wall.py tests/test_preview_wall_session_lifecycle.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add backend/app/services/preview_wall.py backend/app/api/preview_wall.py backend/tests/test_preview_wall_session_lifecycle.py
git commit -m "feat: track preview wall slot sessions"
```

---

### Task 4: HIK bridge stream lifecycle

**Files:**
- Modify: `backend/app/api/hik_media.py`
- Modify: `backend/app/services/hik_media_proxy.py`
- Create: `backend/tests/test_hik_media_session_lifecycle.py`
- Preserve: `backend/tests/test_hik_media_proxy.py`

**Interfaces:**
- Consumes: `camera_media_session_registry.register/unregister`
- Produces: `HikRegisteredStream.close() -> Awaitable[None]`, idempotent best-effort DELETE
- Produces: `HikRegisteredStream.iter_bytes() -> AsyncIterator[bytes]`

- [ ] **Step 1: Write failing HIK lifecycle tests**

Create a fake bridge client where `create_stream()` returns `stream-1`, `iter_media()` yields `b"payload"`, and `stop_stream()` records calls. Test that route-created sessions register under the route camera ID and that invoking the registered closer immediately records `stream-1`.

- [ ] **Step 2: Write the natural/external cleanup race test**

```python
@pytest.mark.asyncio
async def test_hik_registered_stream_close_is_idempotent() -> None:
    client = FakeBridgeClient()
    stream = HikRegisteredStream(client, "stream-1")

    await stream.close()
    await stream.close()

    assert client.stopped == ["stream-1"]
```

Add a second test that consumes `iter_bytes()` to completion after an external `close()` and asserts cleanup failure is not propagated.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run pytest tests/test_hik_media_session_lifecycle.py -q
```

Expected: failure because HIK active streams are not registry-owned and `HikRegisteredStream` does not exist.

- [ ] **Step 4: Implement `HikRegisteredStream`**

In `hik_media_proxy.py`:

```python
import asyncio


class HikRegisteredStream:
    def __init__(self, client, stream_id: str) -> None:
        self._client = client
        self._stream_id = stream_id
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            with suppress(Exception):
                await self._client.stop_stream(self._stream_id)

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._client.iter_media(self._stream_id):
                if chunk:
                    yield chunk
        finally:
            await self.close()
```

Keep `iter_hik_stream(client, stream_id)` as the compatibility wrapper:

```python
async def iter_hik_stream(client, stream_id: str) -> AsyncIterator[bytes]:
    registered = HikRegisteredStream(client, stream_id)
    async for chunk in registered.iter_bytes():
        yield chunk
```

- [ ] **Step 5: Register the HIK session in the API**

After `create_stream()` succeeds:

```python
registered = HikRegisteredStream(client, stream_id)
session_id = await camera_media_session_registry.register(camera_id, registered.close)

async def registered_iter():
    try:
        async for chunk in registered.iter_bytes():
            yield chunk
    finally:
        await registered.close()
        await camera_media_session_registry.unregister(camera_id, session_id)
```

Return `StreamingResponse(registered_iter(), ...)` with current headers unchanged.

- [ ] **Step 6: Run HIK lifecycle + existing proxy tests**

```bash
uv run pytest tests/test_hik_media_session_lifecycle.py tests/test_hik_media_proxy.py -q
uv run ruff check app/api/hik_media.py app/services/hik_media_proxy.py tests/test_hik_media_session_lifecycle.py
```

Expected: PASS, including empty-chunk and cleanup-failure regressions.

- [ ] **Step 7: Commit Task 4**

```bash
git add backend/app/api/hik_media.py backend/app/services/hik_media_proxy.py backend/tests/test_hik_media_session_lifecycle.py
git commit -m "feat: track HIK bridge media sessions"
```

---

### Task 5: RuntimeCoordinator teardown integration

**Files:**
- Modify: `backend/app/services/camera_runtime_coordinator.py`
- Modify: `backend/tests/test_camera_runtime_coordinator.py`
- Create: `backend/tests/test_camera_runtime_media_lifecycle.py`

**Interfaces:**
- Consumes singleton `camera_media_session_registry`
- `CameraRuntimeCoordinator.stop_all(camera_id, ...)` calls `await camera_media_session_registry.stop_camera(camera_id)` before motion/event/recorder/schedule teardown
- `restore()` has no registry calls

- [ ] **Step 1: Add failing teardown-order test**

```python
@pytest.mark.asyncio
async def test_stop_all_stops_media_before_device_runtime(monkeypatch) -> None:
    calls: list[str] = []

    async def stop_media(camera_id: int) -> None:
        calls.append(f"media-stop:{camera_id}")

    monkeypatch.setattr(
        runtime_module.camera_media_session_registry,
        "stop_camera",
        stop_media,
    )
    _patch_stop_dependencies(monkeypatch, calls, running=True, owner="manual")

    await runtime_module.CameraRuntimeCoordinator().stop_all(7)

    assert calls == [
        "media-stop:7",
        "motion-stop:7",
        "event-end:7",
        "event-stop:7",
        "recorder-stop:7",
        "schedule-detach:7",
    ]
```

- [ ] **Step 2: Add restore-negative test**

Patch `camera_media_session_registry.stop_camera` and `stop_all` with async functions that raise `AssertionError`, call `restore()` directly with a valid snapshot/enabled camera, and assert restore completes through the existing recorder/schedule/event/motion path without touching the registry.

- [ ] **Step 3: Run coordinator tests and confirm RED**

```bash
uv run pytest tests/test_camera_runtime_coordinator.py tests/test_camera_runtime_media_lifecycle.py -q
```

Expected: teardown-order test fails because media registry teardown is not yet called.

- [ ] **Step 4: Integrate registry teardown at the top of `stop_all()`**

```python
from app.services.camera_media_session_registry import camera_media_session_registry


async def stop_all(
    self,
    camera_id: int,
    *,
    forget_schedule: bool = False,
) -> RuntimeStopSnapshot:
    snapshot = RuntimeStopSnapshot(
        was_recording=recorder_manager.is_running(camera_id),
        recording_owner=recording_schedule_manager.recording_owner(camera_id),
    )
    await camera_media_session_registry.stop_camera(camera_id)
    await motion_detection_manager.stop_camera(camera_id)
    event_recording_manager.end_event(camera_id)
    await event_recording_manager.stop_camera(camera_id)
    if snapshot.was_recording:
        await recorder_manager.stop(camera_id)
    if forget_schedule:
        recording_schedule_manager.forget(camera_id)
    else:
        recording_schedule_manager.detach_for_runtime_reload(camera_id)
    return snapshot
```

Leave `restore()` unchanged.

- [ ] **Step 5: Verify existing API callers still inherit coordinator teardown**

```bash
uv run pytest \
  tests/test_camera_runtime_coordinator.py \
  tests/test_camera_runtime_restore.py \
  tests/test_camera_adapter_switch_api.py \
  tests/test_camera_adapter_switch_transaction.py \
  tests/test_camera_deletion.py -q
```

Expected: PASS. These suites prove update/switch/delete paths still route through the coordinator; the new coordinator-order test proves those calls now invalidate active media sessions first.

- [ ] **Step 6: Commit Task 5**

```bash
git add backend/app/services/camera_runtime_coordinator.py backend/tests/test_camera_runtime_coordinator.py backend/tests/test_camera_runtime_media_lifecycle.py
git commit -m "feat: stop active media before camera runtime reload"
```

---

### Task 6: Cross-path regression, docs, and final verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`
- Review all changed files from Tasks 1-5

**Interfaces:**
- No new production interface; this task closes the slice and records verified status.

- [ ] **Step 1: Confirm required lifecycle evidence is covered**

Before changing docs, verify tests explicitly cover all of these statements:

```text
detail preview registered -> coordinator/media stop -> FFmpeg close
preview wall camera A/B -> stop A -> A closes and B remains
HIK stream registered -> coordinator/media stop -> bridge DELETE
restore() -> no preview/media registry calls
invalid adapter target -> validation fails before coordinator stop
```

If one statement lacks direct coverage, add exactly one focused regression to the corresponding lifecycle test file before continuing.

- [ ] **Step 2: Run focused lifecycle suite**

```bash
uv run pytest \
  tests/test_camera_media_session_registry.py \
  tests/test_camera_preview_session_lifecycle.py \
  tests/test_preview_wall_session_lifecycle.py \
  tests/test_hik_media_session_lifecycle.py \
  tests/test_camera_runtime_coordinator.py \
  tests/test_camera_runtime_restore.py -q
```

Expected: PASS.

- [ ] **Step 3: Run backend quality locally when available**

```bash
uv run python -m compileall app
uv run ruff check app tests migrations ci_test_shards.py
```

Expected: PASS.

- [ ] **Step 4: Update migration status documentation**

Change these Switch items to checked:

```markdown
- [x] Terminate already-active preview sessions when a Camera is disabled or reloaded.
- [x] Release adapter-specific temporary sessions on disable/reload, especially HIK bridge streams.
```

Add a new verification subsection only after final CI succeeds. Do not mark frontend reconnect, persistent HIK session inventory, or Contract cleanup complete.

- [ ] **Step 5: Open a draft PR and run full GitHub Actions**

Final-head required results:

```text
changes: success
backend-quality: success
backend-tests (0): success
backend-tests (1): success
backend-tests (2): success
backend-tests (3): success
docker-smoke: success
backend aggregate: success
frontend: skipped unless a frontend file changed unexpectedly
```

Docker smoke must include database migration compatibility even though this slice adds no schema migration.

- [ ] **Step 6: Final diff review**

Verify all of the following:

```text
no frontend files changed
no database migration added
no persistent session table added
no recorder/schedule/motion/event ownership redesign
no credential leakage in logs or tests
HIK natural cleanup remains best-effort
preview fallback behavior remains intact
no unresolved PR review threads
```

- [ ] **Step 7: Update PR body with final verification evidence**

The PR body must name the exact final head SHA and CI run number/id and state which jobs passed. Do not claim GREEN until the latest head run has completed successfully.

- [ ] **Step 8: Mark PR ready and merge after final GREEN**

Use the established repository workflow: once the latest head is fully green, mark the PR ready and merge to `main` without requesting a separate merge confirmation.
