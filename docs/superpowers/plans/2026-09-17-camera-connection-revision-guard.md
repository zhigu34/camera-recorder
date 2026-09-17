# Camera Connection Revision Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent recorder, motion, and event pre-roll workers from reconnecting with a stale CameraConnection revision.

**Architecture:** Persisted `CameraConnection.revision` is the generation token. Runtime configs capture that revision, a shared tri-state checker compares it with the current database state, and each reconnecting worker exits normally only when staleness is confirmed. `CameraRuntimeCoordinator` remains the primary stop/reload mechanism; the revision guard is the race/failure safety net.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, asyncio, pytest/pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-09-17-camera-connection-revision-guard-design.md`

## Global Constraints

- `CameraConnection.revision` remains the canonical generation number.
- `None` revision preserves legacy/test compatibility and is treated as current.
- Only confirmed `stale` state terminates a worker; lookup failures return `unknown`.
- Stale exit must not be reported as a camera connectivity/device failure.
- The restored PR #60 event pre-roll ownership behavior must remain unchanged.
- Do not add preview-session termination, HIK temporary-session release, adapter switching, or cross-process coordination in this slice.

---

### Task 1: Shared Revision State and Runtime Config Propagation

**Files:**
- Create: `backend/app/services/camera_connection_revision.py`
- Modify: `backend/app/services/ffmpeg_builder.py`
- Modify: `backend/app/services/camera_config.py`
- Modify: `backend/app/services/motion_worker.py`
- Modify: `backend/app/services/motion_manager.py`
- Create: `backend/tests/test_camera_connection_revision_guard.py`

**Interfaces:**
- Produces: `RevisionState = Literal["current", "stale", "unknown"]`
- Produces: `async def connection_revision_state(camera_id: int, expected_revision: int | None) -> RevisionState`
- Produces: `CameraRuntimeConfig.connection_revision: int | None = None`
- Produces: `MotionWorkerConfig.connection_revision: int | None = None`

- [x] **Step 1: Write failing checker/runtime-config tests**

Cover these exact cases in `test_camera_connection_revision_guard.py`:

```python
assert await connection_revision_state(camera.id, None) == "current"
assert await connection_revision_state(camera.id, camera.connection.revision) == "current"
assert await connection_revision_state(camera.id, camera.connection.revision + 1) == "stale"
# disabled/missing Camera and missing current connection with expected revision -> stale
# SessionLocal/lookup exception -> unknown
assert runtime_config(camera).connection_revision == camera.connection.revision
```

Also assert `_default_config_loader()` produces `MotionWorkerConfig.connection_revision` from `camera.connection.revision`.

- [x] **Step 2: Run focused tests and verify RED**

Run through CI or locally:

```bash
cd backend
uv run pytest tests/test_camera_connection_revision_guard.py -q
```

Expected: import/attribute failures because the checker and config fields do not exist.

- [x] **Step 3: Implement the tri-state checker**

Create `camera_connection_revision.py` with this contract:

```python
from typing import Literal

RevisionState = Literal["current", "stale", "unknown"]

async def connection_revision_state(camera_id: int, expected_revision: int | None) -> RevisionState:
    if expected_revision is None:
        return "current"
    try:
        async with SessionLocal() as db:
            camera = await db.get(Camera, camera_id)
    except Exception:
        return "unknown"
    if camera is None or not camera.enabled or camera.connection is None:
        return "stale"
    return "current" if camera.connection.revision == expected_revision else "stale"
```

Do not mutate Camera or connection rows.

- [x] **Step 4: Propagate revision into runtime configs**

Add optional fields at the end of both dataclasses:

```python
connection_revision: int | None = None
```

Populate with:

```python
connection_revision=(camera.connection.revision if camera.connection is not None else None)
```

in `camera_config.runtime_config()` and `motion_manager._default_config_loader()`.

- [x] **Step 5: Run focused tests and existing config tests**

```bash
cd backend
uv run pytest tests/test_camera_connection_revision_guard.py tests/test_ffmpeg_builder.py tests/test_motion_manager.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/services/camera_connection_revision.py backend/app/services/ffmpeg_builder.py backend/app/services/camera_config.py backend/app/services/motion_worker.py backend/app/services/motion_manager.py backend/tests/test_camera_connection_revision_guard.py
git commit -m "feat: propagate camera connection revision"
```

---

### Task 2: Recorder Reconnect Guard

**Files:**
- Modify: `backend/app/services/recorder_manager.py`
- Create: `backend/tests/test_recorder_revision_guard.py`

**Interfaces:**
- Consumes: `connection_revision_state(camera_id, expected_revision)` from Task 1.
- Behavior: `CameraWorker` may spawn FFmpeg only when revision state is not `stale`.

- [x] **Step 1: Write failing recorder tests**

Use a `CameraRuntimeConfig(connection_revision=7)` and monkeypatch the revision checker plus `asyncio.create_subprocess_exec`.

Required assertions:

```python
# stale before first attempt
await worker._run_loop()
assert spawn_calls == []
assert worker.restart_count == 0
assert worker.consecutive_failure_count == 0
assert worker.state == "STOPPED"
```

Add a reconnect test where first check is `current`, the fake process exits, and the next check is `stale`; assert only one FFmpeg spawn occurs. Add a `None` revision test proving legacy config still reaches spawn logic.

- [x] **Step 2: Run test and verify RED**

```bash
cd backend
uv run pytest tests/test_recorder_revision_guard.py -q
```

Expected: stale configs still reach FFmpeg spawn/reconnect.

- [x] **Step 3: Guard each recorder spawn**

At the top of each `_run_loop()` iteration, before state changes/spawn failure accounting:

```python
revision_state = await connection_revision_state(
    self.camera.id,
    self.camera.connection_revision,
)
if revision_state == "stale":
    break
if revision_state == "unknown":
    await self._log("connection revision check unavailable; preserving current retry behavior")
```

Do not call `_mark_disconnected`, `_check_failure_streak`, or increment counters for stale exit.

- [x] **Step 4: Run recorder tests**

```bash
cd backend
uv run pytest tests/test_recorder_revision_guard.py tests/test_camera_enabled_runtime_guard.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/recorder_manager.py backend/tests/test_recorder_revision_guard.py
git commit -m "feat: stop stale recorder reconnects"
```

---

### Task 3: Motion Supervisor Revision Guard

**Files:**
- Modify: `backend/app/services/motion_manager.py`
- Create: `backend/tests/test_motion_revision_guard.py`

**Interfaces:**
- Consumes: `MotionWorkerConfig.connection_revision` and `connection_revision_state()`.
- Behavior: confirmed stale revision ends `_supervise()` before another worker attempt.

- [x] **Step 1: Write failing motion tests**

Construct `MotionDetectionManager` with a fake worker factory and `MotionWorkerConfig(connection_revision=11)`.

Required behavior:

```python
# checker returns stale before first attempt
await manager._supervise(config)
assert worker_factory_calls == []
assert manager.status(config.camera_id)["state"] == "stopped"
```

Add a reconnect case where the first worker raises a device error, retry delay completes, and the next revision check returns `stale`; assert a second worker is never created. Add `unknown` coverage proving it does not become the worker's device error.

- [x] **Step 2: Run and verify RED**

```bash
cd backend
uv run pytest tests/test_motion_revision_guard.py -q
```

Expected: worker factory is still called for stale revisions.

- [x] **Step 3: Add supervisor guard**

Before `worker_factory(...)` in every loop iteration:

```python
revision_state = await connection_revision_state(camera_id, config.connection_revision)
if revision_state == "stale":
    self._set_status(camera_id, "stopped", stream=None, last_error=None)
    break
```

For `unknown`, preserve the existing supervisor path and do not overwrite `last_error` with a revision-check/database error.

- [x] **Step 4: Run motion tests**

```bash
cd backend
uv run pytest tests/test_motion_revision_guard.py tests/test_motion_manager.py tests/test_motion_worker.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/motion_manager.py backend/tests/test_motion_revision_guard.py
git commit -m "feat: stop stale motion reconnects"
```

---

### Task 4: Event Ring Revision Guard

**Files:**
- Modify: `backend/app/services/event_recording.py`
- Create: `backend/tests/test_event_recording_revision_guard.py`
- Regression: `backend/tests/test_event_recording_handoff.py`

**Interfaces:**
- `EventBufferWorker.__init__` gains `connection_revision: int | None = None`.
- Reconcile compares both `worker.stream_uri` and `worker.connection_revision`.

- [x] **Step 1: Write failing event-ring tests**

Required cases:

```python
# stale before spawn -> no subprocess
worker = EventBufferWorker(..., connection_revision=4)
await worker._run()
assert spawn_calls == []

# same URI, revision changes 4 -> 5 during reconcile
await manager.reconcile_once()
assert old_worker.stop_calls == 1
assert new_worker.connection_revision == 5
```

Also cover `None` compatibility and verify active-event capture ownership is not cleared by worker replacement logic.

- [x] **Step 2: Run and verify RED**

```bash
cd backend
uv run pytest tests/test_event_recording_revision_guard.py tests/test_event_recording_handoff.py -q
```

Expected: stale event worker still spawns and reconcile reuses same-URI old worker.

- [x] **Step 3: Add event worker guard**

Store `connection_revision` on `EventBufferWorker`. At the top of its reconnect loop:

```python
revision_state = await connection_revision_state(self.camera_id, self.connection_revision)
if revision_state == "stale":
    break
```

`unknown` preserves current retry behavior.

- [x] **Step 4: Make reconcile revision-aware**

Build eligibility as `(camera, stream_uri, connection_revision)` where:

```python
connection_revision = camera.connection.revision if camera.connection is not None else None
```

Reuse an existing running worker only when both URI and revision match. Pass revision into every new `EventBufferWorker`.

Do not alter `_capture_required`, `event_capture_required()`, or PR #60 handoff ordering.

- [x] **Step 5: Run focused and handoff tests**

```bash
cd backend
uv run pytest tests/test_event_recording_revision_guard.py tests/test_event_recording_handoff.py tests/test_event_recording.py -q
```

If `test_event_recording.py` does not exist, run the existing event recording test files selected by pytest collection instead; the required regression file remains `test_event_recording_handoff.py`.

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/services/event_recording.py backend/tests/test_event_recording_revision_guard.py
git commit -m "feat: stop stale event buffer reconnects"
```

---

### Task 5: Migration Checklist and Full Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`
- Modify: `docs/superpowers/plans/2026-09-17-camera-connection-revision-guard.md`

- [x] **Step 1: Mark only this guard complete**

Update the migration checklist to mark long-running recorder/motion/event reconnects protected by `CameraConnection.revision`. Keep preview-session termination, HIK session release, adapter switching, and other remaining work unchecked.

- [x] **Step 2: Run complete verification**

CI must show:

```text
backend-quality: success
backend-tests (0): success
backend-tests (1): success
backend-tests (2): success
backend-tests (3): success
backend aggregate: success
docker-smoke: success
frontend: success or correctly skipped by path filter when no frontend diff
```

Specifically confirm `test_event_recording_handoff.py` remains green.

- [x] **Step 3: Update plan checkboxes and commit docs**

```bash
git add docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md docs/superpowers/plans/2026-09-17-camera-connection-revision-guard.md
git commit -m "docs: complete camera connection revision guard"
```

- [ ] **Step 4: Open/finish PR only after fresh final-head CI**

Keep the PR scoped to the revision guard slice and merge only after the final head has fresh successful CI evidence.
