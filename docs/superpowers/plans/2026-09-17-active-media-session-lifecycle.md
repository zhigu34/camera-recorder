# Active Media Session Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make detail previews, preview-wall slots, and HIK bridge streams camera-scoped runtime resources that are terminated immediately by camera disable, reload, deletion, or adapter switch without being recreated by runtime restore.

**Architecture:** Add a process-local `CameraMediaSessionRegistry` that owns only session membership and invokes async close callbacks best-effort. Detail preview, preview-wall slot, and HIK internal-media lifetimes register with this registry; `CameraRuntimeCoordinator.stop_all()` calls `stop_camera(camera_id)` before motion/event/recorder/schedule teardown, while `restore()` remains preview-agnostic.

**Tech Stack:** FastAPI, asyncio, SQLAlchemy async ORM, FFmpeg subprocesses, httpx, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-17-active-media-session-lifecycle-design.md`

## Global Constraints

- Target behavior is option A from the approved design: disable, reload, deletion, and adapter switch immediately terminate active preview/media sessions; users reopen previews explicitly.
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
- Modify `backend/app/services/camera_preview.py`: make detail-preview session close public and idempotent; provide a registry-aware stream wrapper boundary.
- Modify `backend/app/api/cameras.py`: register detail preview after a successful open and unregister on stream completion.
- Modify `backend/app/services/preview_wall.py`: introduce a slot session object that owns one FFmpeg process and exposes `stream()` + `close()`.
- Modify `backend/app/api/preview_wall.py`: register each slot by `camera_id` and unregister independently.
- Modify `backend/app/api/hik_media.py`: register HIK bridge `stream_id` after creation and unregister in iterator finalization.
- Modify `backend/app/services/hik_media_proxy.py`: keep existing iterator semantics; allow an external closer to race safely with natural cleanup.
- Modify `backend/app/services/camera_runtime_coordinator.py`: call media-session teardown first in `stop_all()` only; leave `restore()` preview-agnostic.
- Create focused lifecycle tests instead of overloading unrelated API suites.
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
- Produces: `CameraMediaSessionRegistry.stop_camera(camera_id: int) -> None`
- Produces: `CameraMediaSessionRegistry.stop_all() -> None`
- Produces singleton: `camera_media_session_registry`

- [ ] **Step 1: Write the failing registry tests**

Create tests that exercise camera isolation, atomic detach, idempotent unregister, best-effort closer failures, and global drain. Use closers that append to a call list and an `asyncio.Event` to prove sessions registered during cleanup survive the current stop generation.

```python
@pytest.mark.asyncio
async def test_stop_camera_closes_only_detached_target_sessions() -> None:
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
```

Also add:

```python
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
```

Use a small `active_count(camera_id)` test/diagnostic method rather than reaching into private dict state.

- [ ] **Step 2: Run the new test file and confirm RED**

Run from `backend/`:

```bash
uv run pytest tests/test_camera_media_session_registry.py -q
```

Expected: collection/import failure because `camera_media_session_registry.py` and `CameraMediaSessionRegistry` do not exist.

- [ ] **Step 3: Implement the minimal registry**

Use an `asyncio.Lock`, a monotonic in-process `session_id` source such as `uuid.uuid4().hex`, and detach maps under the lock before awaiting closers.

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

    async def _close_detached(self, camera_id: int, sessions: dict[str, SessionCloser]) -> None:
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

- [ ] **Step 4: Run registry tests and relevant quality checks**

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
- Produces: idempotent `PreviewSession.close() -> None`
- Produces: response iterator that always unregisters its registry entry in `finally`

- [ ] **Step 1: Write failing session-close unit tests**

Use a fake process that records `terminate`, `wait`, and `kill`. Prove two calls to `PreviewSession.close()` only perform process teardown once and that `stream()` calling `close()` after an external close is safe.

```python
@pytest.mark.asyncio
async def test_preview_session_close_is_idempotent() -> None:
    process = FakeProcess()
    session = PreviewSession(process=process, first_chunk=b"frame")

    await session.close()
    await session.close()

    assert process.terminate_calls == 1
```

- [ ] **Step 2: Write failing endpoint registration/unregister tests**

Monkeypatch `open_mjpeg_preview()` to return a fake session with `close()` and `stream()`, and monkeypatch the registry singleton used by `app.api.cameras`. Call `preview_camera()` directly with a temporary DB/session setup or use the existing FastAPI test fixture. Assert registration uses the requested `camera_id`, then consume/close the streaming iterator and assert `unregister(camera_id, session_id)` runs.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run pytest tests/test_camera_preview_session_lifecycle.py -q
```

Expected: failures because `PreviewSession.close()` is not a public idempotent method and the endpoint does not register sessions.

- [ ] **Step 4: Implement idempotent PreviewSession.close()**

Add an internal guard on `PreviewSession` and make `stream()` delegate final cleanup to `close()`.

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
            ...
        finally:
            await self.close()
```

Use `field(default_factory=asyncio.Lock)` so locks are not shared between sessions.

- [ ] **Step 5: Register and unregister detail preview in the camera endpoint**

After the final preview session (including auto-fallback selection) is successfully opened:

```python
session_id = await camera_media_session_registry.register(camera_id, session.close)

async def registered_stream():
    try:
        async for chunk in session.stream():
            yield chunk
    finally:
        await camera_media_session_registry.unregister(camera_id, session_id)
```

Return `StreamingResponse(registered_stream(), ...)` without otherwise changing preview headers/fallback behavior.

- [ ] **Step 6: Run focused and existing preview tests**

```bash
uv run pytest tests/test_camera_preview_session_lifecycle.py tests/test_camera_preview.py -q
uv run ruff check app/services/camera_preview.py app/api/cameras.py tests/test_camera_preview_session_lifecycle.py
```

Expected: PASS; existing command/path/fallback tests remain unchanged.

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
- Produces: `WallPreviewSession(source: WallPreviewSource)` with `stream(on_frame)` and idempotent `close()`
- Each API slot registers independently under `slot.camera_id`

- [ ] **Step 1: Write failing WallPreviewSession tests**

Move process ownership from `stream_preview_frames()` into a session object. The tests must prove external `close()` terminates the process and natural `stream()` finalization is idempotent.

```python
@pytest.mark.asyncio
async def test_wall_preview_session_close_terminates_owned_process_once(monkeypatch) -> None:
    session = WallPreviewSession(source)
    process = FakeProcess(...)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn(process))

    streaming = asyncio.create_task(session.stream(on_frame))
    await process.started.wait()
    await session.close()
    await streaming

    assert process.terminate_calls == 1
```

- [ ] **Step 2: Write failing multi-slot registry isolation test**

Build two slot sessions for cameras 10 and 11. Register them independently, invoke `camera_media_session_registry.stop_camera(10)`, and assert camera 10's slot finishes while camera 11 remains active. The WebSocket itself must not be closed by the registry.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run pytest tests/test_preview_wall_session_lifecycle.py -q
```

Expected: FAIL because the current service exposes only `stream_preview_frames()` and API tasks are not registry-owned.

- [ ] **Step 4: Introduce WallPreviewSession without changing parser/command behavior**

The session should spawn lazily in `stream()` and hold its process for external close:

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
        self._process = await _open_process(self.source)
        try:
            ...existing JPEG parser/read loop...
        finally:
            await self.close()
```

Keep a compatibility `stream_preview_frames(source, on_frame)` wrapper if existing callers/tests outside the API depend on it:

```python
async def stream_preview_frames(source, on_frame):
    await WallPreviewSession(source).stream(on_frame)
```

- [ ] **Step 5: Wire each wall slot through the registry**

In `app.api.preview_wall`, construct a `WallPreviewSession` for the primary source and another only when fallback is actually needed. Register the currently active session under `slot.camera_id`, unregister it in `finally`, and when switching from sub to main fallback unregister/close the failed primary before registering the fallback session.

Do not close the WebSocket from the registry callback; only the slot's process/task should end.

- [ ] **Step 6: Run focused + existing wall tests**

```bash
uv run pytest tests/test_preview_wall_session_lifecycle.py tests/test_preview_wall.py -q
uv run ruff check app/services/preview_wall.py app/api/preview_wall.py tests/test_preview_wall_session_lifecycle.py
```

Expected: PASS; existing JPEG parsing/status/fallback semantics remain green.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/app/services/preview_wall.py backend/app/api/preview_wall.py backend/tests/test_preview_wall_session_lifecycle.py
git commit -m "feat: track preview wall slot sessions"
```

---

### Task 4: HIK bridge stream lifecycle

**Files:**
- Modify: `backend/app/api/hik_media.py`
- Modify: `backend/app/services/hik_media_proxy.py` only if needed for an explicit shared closer helper
- Create: `backend/tests/test_hik_media_session_lifecycle.py`
- Preserve: `backend/tests/test_hik_media_proxy.py`

**Interfaces:**
- Consumes: `camera_media_session_registry.register/unregister`
- HIK closer: async callback that invokes `HikBridgeClient.stop_stream(stream_id)` best-effort
- Natural iterator cleanup and registry-triggered cleanup may race safely

- [ ] **Step 1: Write failing HIK API lifecycle tests**

Monkeypatch `HikBridgeClient.create_stream()` to return `stream-1`, provide an iterator that stays open, and spy on registry registration. Assert the endpoint registers only after stream creation succeeds and associates the session with the route `camera_id`.

Add a test that invokes the registered closer and proves `stop_stream("stream-1")` is called immediately.

- [ ] **Step 2: Write a race/idempotency regression test**

Simulate external registry close followed by iterator `aclose()`. `stop_stream()` may be invoked twice at the client boundary, but neither call may propagate and the registry must unregister cleanly. Prefer making the API closer itself idempotent so only one DELETE is attempted per backend session.

```python
class HikRegisteredStream:
    def __init__(self, client, stream_id):
        self._client = client
        self._stream_id = stream_id
        self._closed = False
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            with suppress(Exception):
                await self._client.stop_stream(self._stream_id)
```

The wrapper can live in `hik_media_proxy.py` if keeping API code thin improves clarity.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
uv run pytest tests/test_hik_media_session_lifecycle.py -q
```

Expected: FAIL because active HIK streams are not registered by camera.

- [ ] **Step 4: Implement registry-aware HIK stream response**

After `create_stream()` succeeds:

```python
registered = HikRegisteredStream(client, stream_id)
session_id = await camera_media_session_registry.register(camera_id, registered.close)

async def registered_iter():
    try:
        async for chunk in iter_hik_stream(client, stream_id, closer=registered.close):
            yield chunk
    finally:
        await registered.close()
        await camera_media_session_registry.unregister(camera_id, session_id)
```

If adding a `closer` parameter to `iter_hik_stream`, preserve its defaults so existing tests/callers still use the current best-effort stop semantics.

- [ ] **Step 5: Run HIK lifecycle + existing proxy tests**

```bash
uv run pytest tests/test_hik_media_session_lifecycle.py tests/test_hik_media_proxy.py -q
uv run ruff check app/api/hik_media.py app/services/hik_media_proxy.py tests/test_hik_media_session_lifecycle.py
```

Expected: PASS, including existing empty-chunk and cleanup-failure tests.

- [ ] **Step 6: Commit Task 4**

```bash
git add backend/app/api/hik_media.py backend/app/services/hik_media_proxy.py backend/tests/test_hik_media_session_lifecycle.py
git commit -m "feat: track HIK bridge media sessions"
```

---

### Task 5: RuntimeCoordinator teardown integration

**Files:**
- Modify: `backend/app/services/camera_runtime_coordinator.py`
- Modify: `backend/tests/test_camera_runtime_coordinator.py`
- Modify or create: `backend/tests/test_camera_runtime_media_lifecycle.py`

**Interfaces:**
- Consumes singleton `camera_media_session_registry`
- `CameraRuntimeCoordinator.stop_all(camera_id, ...)` must call `await camera_media_session_registry.stop_camera(camera_id)` before motion/event/recorder/schedule teardown
- `restore()` has no registry calls

- [ ] **Step 1: Add the failing teardown-order test**

Extend `_patch_stop_dependencies()` or create a dedicated test seam so the first call is media teardown:

```python
@pytest.mark.asyncio
async def test_stop_all_stops_media_sessions_before_device_runtime(monkeypatch) -> None:
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

- [ ] **Step 2: Add failing restore-negative test**

Patch registry `register`, `stop_camera`, and `stop_all` to raise `AssertionError` if called, then invoke `restore()` on an enabled camera and assert only existing recorder/schedule/event/motion restoration occurs.

- [ ] **Step 3: Run coordinator tests and confirm RED**

```bash
uv run pytest tests/test_camera_runtime_coordinator.py tests/test_camera_runtime_media_lifecycle.py -q
```

Expected: teardown-order test fails because media registry is not yet called.

- [ ] **Step 4: Add the registry call at the top of stop_all()**

```python
from app.services.camera_media_session_registry import camera_media_session_registry

async def stop_all(...):
    snapshot = RuntimeStopSnapshot(...)
    await camera_media_session_registry.stop_camera(camera_id)
    await motion_detection_manager.stop_camera(camera_id)
    ...
```

Do not add registry calls to `restore()`.

- [ ] **Step 5: Verify existing caller inheritance**

Run the existing API tests that cover update/disable/delete and adapter switch, plus the coordinator suite. The important regression is that those paths still call `stop_all()`/`reload()` rather than bypassing the coordinator.

```bash
uv run pytest \
  tests/test_camera_runtime_coordinator.py \
  tests/test_camera_runtime_restore.py \
  tests/test_camera_adapter_switch_api.py \
  tests/test_camera_adapter_switch_transaction.py \
  tests/test_camera_deletion.py -q
```

If the exact deletion test filename differs, use the existing camera-deletion suite discovered in `backend/tests` rather than creating duplicate coverage.

- [ ] **Step 6: Commit Task 5**

```bash
git add backend/app/services/camera_runtime_coordinator.py backend/tests/test_camera_runtime_coordinator.py backend/tests/test_camera_runtime_media_lifecycle.py
git commit -m "feat: stop active media before camera runtime reload"
```

---

### Task 6: Cross-path regression, docs, and final verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`
- Review all changed backend/test files from Tasks 1-5

**Interfaces:**
- No new production interface; this task closes the slice and records verified status.

- [ ] **Step 1: Add any missing end-to-end lifecycle regression discovered during review**

Before changing docs, review the diff against the spec success criteria. If API-level coverage does not yet prove a camera lifecycle call reaches registry teardown, add one focused regression using the existing API fixture rather than duplicating endpoint behavior.

Minimum accepted evidence must cover:

```text
detail preview registered -> coordinator stop -> FFmpeg close
preview wall camera A/B -> stop A -> A closes, B remains
HIK stream registered -> coordinator stop -> bridge DELETE
restore() -> no preview/media registration
invalid adapter target -> validation fails before coordinator stop (existing switch test stays green)
```

- [ ] **Step 2: Run focused lifecycle tests**

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

- [ ] **Step 3: Run repository backend quality locally when available**

```bash
uv run python -m compileall app
uv run ruff check app tests migrations ci_test_shards.py
```

Expected: PASS.

- [ ] **Step 4: Update migration status documentation only after focused GREEN**

In `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md` mark these two Switch items complete:

```markdown
- [x] Terminate already-active preview sessions when a Camera is disabled or reloaded.
- [x] Release adapter-specific temporary sessions on disable/reload, especially HIK bridge streams.
```

Add a verification subsection naming the final CI run only after it completes successfully. Do not mark frontend reconnect or Contract cleanup complete.

- [ ] **Step 5: Open/update the PR and run full GitHub Actions**

Required final head evidence:

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

Docker smoke must include database migration compatibility even though this slice has no schema migration.

- [ ] **Step 6: Final diff review**

Verify:

- no frontend files changed;
- no database migration added;
- no persistent session table added;
- no recorder/schedule/motion/event ownership redesign;
- no credential leakage in logs or tests;
- HIK natural cleanup remains best-effort;
- preview fallback behavior remains intact;
- PR has no unresolved review threads.

- [ ] **Step 7: Mark PR ready and merge after final GREEN**

Use the already established repository workflow: after latest-head CI is fully green, mark the PR ready and merge to `main` without asking for a separate merge confirmation.
