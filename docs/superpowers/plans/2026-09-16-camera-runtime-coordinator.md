# Camera Runtime Coordinator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize per-camera recorder, schedule, motion, and event-buffer lifecycle so connection edits and enable/disable changes no longer coordinate runtime workers independently in API handlers.

**Architecture:** Add `CameraRuntimeCoordinator` as the only service that performs a per-camera stop/reload sequence for the existing recorder, recording-schedule, event-recording, and motion managers. The coordinator snapshots recording ownership before stopping workers, reloads the committed Camera/current connection from the database, leaves disabled cameras completely stopped, and restores either a previous manual recording or the current automatic schedule policy before restarting event buffering and motion detection. This slice deliberately coordinates existing managers rather than rewriting their workers.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, pytest/pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-design.md`

## Global Constraints

- `Camera.id` remains the stable monitoring-point identity.
- `Camera.enabled=false` is the authoritative runtime master switch.
- Connection edits may be saved while the device is offline; runtime reload must not roll back persisted configuration.
- A previously manual-running recorder may be restarted after a connection-only reload.
- Schedule-owned recording is restored by schedule reconciliation, not by directly starting it from API handlers.
- Event pre-roll ownership from an active event must not be truncated by a runtime handoff.
- This slice does not implement HIK adapter persistence, adapter switching, preview-session registries, or connection-revision stale-worker guards; those remain separate follow-on slices.

---

### Task 1: Expose recording ownership without leaking schedule internals

**Files:**
- Modify: `backend/app/services/recording_schedule_manager.py`
- Test: `backend/tests/test_recording_schedule.py`

**Interfaces:**
- Produces: `RecordingScheduleManager.recording_owner(camera_id: int) -> Literal["manual", "schedule"] | None`
- Produces: `RecordingScheduleManager.detach_for_runtime_reload(camera_id: int) -> None`
- Existing `note_manual_start`, `reset_for_schedule_change`, `clear_override`, `forget`, and `reconcile` remain public and keep their current semantics.

- [ ] **Step 1: Write failing ownership tests**

Add focused tests that construct a `RecordingScheduleManager`, seed `_manual_running` / `_managed`, and assert:

```python
assert manager.recording_owner(1) is None
manager._manual_running.add(1)
assert manager.recording_owner(1) == "manual"
manager._manual_running.clear()
manager._managed.add(1)
assert manager.recording_owner(1) == "schedule"
```

Add a detach test:

```python
manager._managed.add(1)
manager._manual_running.add(2)
manager._manual_paused.add(3)
manager.detach_for_runtime_reload(1)
assert 1 not in manager._managed
assert 2 in manager._manual_running
assert 3 in manager._manual_paused
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
cd backend && uv run pytest tests/test_recording_schedule.py -k 'recording_owner or detach_for_runtime_reload' -v
```

Expected: FAIL because the two methods do not exist.

- [ ] **Step 3: Implement the minimal ownership API**

Add:

```python
from typing import Any, Literal

RecordingOwner = Literal["manual", "schedule"]


def recording_owner(self, camera_id: int) -> RecordingOwner | None:
    if camera_id in self._manual_running:
        return "manual"
    if camera_id in self._managed:
        return "schedule"
    return None


def detach_for_runtime_reload(self, camera_id: int) -> None:
    self._managed.discard(camera_id)
    self._camera_status.pop(camera_id, None)
```

Do not mark the camera manually paused: coordinator-triggered stops are configuration lifecycle operations, not user stop actions.

- [ ] **Step 4: Re-run schedule tests**

Run:

```bash
cd backend && uv run pytest tests/test_recording_schedule.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/recording_schedule_manager.py backend/tests/test_recording_schedule.py
git commit -m "refactor: expose recorder ownership for runtime reload"
```

---

### Task 2: Add CameraRuntimeCoordinator stop/reload orchestration

**Files:**
- Create: `backend/app/services/camera_runtime_coordinator.py`
- Create: `backend/tests/test_camera_runtime_coordinator.py`

**Interfaces:**
- Consumes: `recording_schedule_manager.recording_owner(camera_id)` and `detach_for_runtime_reload(camera_id)` from Task 1.
- Produces: `RuntimeStopSnapshot(was_recording: bool, recording_owner: RecordingOwner | None)`.
- Produces: `CameraRuntimeCoordinator.stop_all(camera_id: int, *, forget_schedule: bool = False) -> RuntimeStopSnapshot`.
- Produces: `CameraRuntimeCoordinator.reload(camera_id: int, *, schedule_changed: bool = False) -> str`, returning one of `"missing"`, `"disabled"`, or `"running"`.
- Produces singleton: `camera_runtime_coordinator`.

- [ ] **Step 1: Write failing coordinator unit tests**

Use monkeypatched manager methods and a fake `SessionLocal` to cover these exact sequences:

1. `stop_all()` snapshots recorder state/ownership, then stops motion, event buffer, recorder, and detaches schedule runtime state.
2. `stop_all(..., forget_schedule=True)` calls `recording_schedule_manager.forget(camera_id)` instead of detach.
3. `reload()` for a missing Camera returns `"missing"` and does not restart anything.
4. `reload()` for `enabled=False` returns `"disabled"`, leaves all workers stopped, and clears schedule ownership.
5. connection-only reload of a previously manual-running Camera restarts through `start_regular_recorder(runtime_config(camera))`, restores `note_manual_start`, then reconciles event buffer and motion.
6. schedule-owned reload does not directly restart recorder; it calls `recording_schedule_manager.reconcile()`, then event-buffer reconcile, then motion restart.
7. `schedule_changed=True` deliberately drops a previous manual override and returns ownership to schedule reconciliation.

Assert the restore order for an enabled camera is:

```text
recording policy -> event buffer -> motion
```

so motion cannot emit a confirmed event before its pre-roll owner has been restored.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
cd backend && uv run pytest tests/test_camera_runtime_coordinator.py -v
```

Expected: collection/import failure because `camera_runtime_coordinator.py` does not exist.

- [ ] **Step 3: Implement coordinator**

Create a `RuntimeStopSnapshot` frozen dataclass and `CameraRuntimeCoordinator` using the existing singletons:

```python
@dataclass(frozen=True)
class RuntimeStopSnapshot:
    was_recording: bool
    recording_owner: RecordingOwner | None


async def stop_all(self, camera_id: int, *, forget_schedule: bool = False) -> RuntimeStopSnapshot:
    snapshot = RuntimeStopSnapshot(
        was_recording=recorder_manager.is_running(camera_id),
        recording_owner=recording_schedule_manager.recording_owner(camera_id),
    )
    await motion_detection_manager.stop_camera(camera_id)
    await event_recording_manager.stop_camera(camera_id)
    if snapshot.was_recording:
        await recorder_manager.stop(camera_id)
    if forget_schedule:
        recording_schedule_manager.forget(camera_id)
    else:
        recording_schedule_manager.detach_for_runtime_reload(camera_id)
    return snapshot
```

`reload()` must call `stop_all()` first, load the Camera fresh from `SessionLocal`, and then:

```python
if camera is None:
    return "missing"
if not camera.enabled:
    recording_schedule_manager.forget(camera_id)
    return "disabled"

if snapshot.recording_owner == "manual" and snapshot.was_recording and not schedule_changed:
    await start_regular_recorder(runtime_config(camera))
    recording_schedule_manager.note_manual_start(camera_id)
else:
    if schedule_changed:
        recording_schedule_manager.reset_for_schedule_change(camera_id)
    await recording_schedule_manager.reconcile()

await event_recording_manager.reconcile_once()
await motion_detection_manager.restart_camera(camera_id)
return "running"
```

Do not swallow runtime restart errors in this service: API callers persist configuration before reload and should surface/log reload failures separately without rolling back committed configuration.

- [ ] **Step 4: Re-run coordinator and existing lifecycle tests**

Run:

```bash
cd backend && uv run pytest \
  tests/test_camera_runtime_coordinator.py \
  tests/test_recorder_event_buffer_handoff.py \
  tests/test_event_recording_handoff.py \
  tests/test_motion_manager.py \
  tests/test_recording_schedule.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/camera_runtime_coordinator.py backend/tests/test_camera_runtime_coordinator.py
git commit -m "feat: add camera runtime coordinator"
```

---

### Task 3: Route Camera and ONVIF lifecycle edits through the coordinator

**Files:**
- Modify: `backend/app/api/cameras.py`
- Modify: `backend/app/api/onvif_cameras.py`
- Test: `backend/tests/test_camera_connection_write.py`
- Test: `backend/tests/test_onvif_camera_api.py`
- Test: `backend/tests/test_camera_deletion.py`

**Interfaces:**
- Consumes: `camera_runtime_coordinator.reload(camera_id, schedule_changed=...)`.
- Consumes: `camera_runtime_coordinator.stop_all(camera_id, forget_schedule=True)`.

- [ ] **Step 1: Write failing API lifecycle tests**

Add tests proving:

- manual RTSP update that changes host/path/password calls one coordinator reload after the database commit.
- metadata-only manual RTSP update does not reload runtime unless `enabled` or schedule policy changed.
- toggling `enabled` always reloads runtime.
- ONVIF re-discovery/update calls coordinator reload instead of directly calling recorder/motion/schedule managers.
- Camera DELETE calls `stop_all(..., forget_schedule=True)` before deleting the row.

Use monkeypatch spies; assert the old direct coordination entry points are not called from the API tests.

- [ ] **Step 2: Run focused tests to verify RED**

Run:

```bash
cd backend && uv run pytest \
  tests/test_camera_connection_write.py \
  tests/test_onvif_camera_api.py \
  tests/test_camera_deletion.py -v
```

Expected: FAIL because API handlers still coordinate managers directly.

- [ ] **Step 3: Replace direct API coordination**

For `update_camera`:

1. capture the pre-update connection revision and relevant policy values.
2. perform `upsert_manual_rtsp_connection` and commit.
3. compute `connection_changed` from revision change.
4. compute `schedule_changed` from `enabled`, `auto_record`, `recording_schedule_enabled`, and `recording_schedule` edits.
5. call coordinator reload when `connection_changed or schedule_changed`.

For `update_onvif_camera`:

1. remove `was_recording` and all direct recorder/motion/schedule restart code.
2. commit the re-discovered connection/config first.
3. call `camera_runtime_coordinator.reload(camera.id, schedule_changed=schedule_changed)` exactly once.

For DELETE:

```python
await camera_runtime_coordinator.stop_all(camera_id, forget_schedule=True)
```

then write the audit event and delete the Camera.

- [ ] **Step 4: Re-run focused tests**

Run the same command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/cameras.py backend/app/api/onvif_cameras.py \
  backend/tests/test_camera_connection_write.py backend/tests/test_onvif_camera_api.py \
  backend/tests/test_camera_deletion.py
git commit -m "refactor: centralize camera runtime reloads"
```

---

### Task 4: Enforce Camera.enabled on device-access entry points

**Files:**
- Modify: `backend/app/api/cameras.py`
- Test: `backend/tests/test_camera_enabled_runtime_guard.py`

**Interfaces:**
- No new service interface.
- Explicit one-shot `/probe` remains allowed while disabled, per the architecture spec.

- [ ] **Step 1: Write failing disabled-camera API tests**

Add tests proving a disabled camera receives HTTP 409 from:

```text
POST /api/cameras/{id}/start
POST /api/cameras/{id}/restart
GET  /api/cameras/{id}/preview.mjpeg
```

Also prove:

```text
POST /api/cameras/{id}/probe
```

is not rejected merely because `enabled=False`.

- [ ] **Step 2: Run focused tests to verify RED**

Run:

```bash
cd backend && uv run pytest tests/test_camera_enabled_runtime_guard.py -v
```

Expected: start/restart/preview tests fail because those handlers do not currently reject disabled Cameras.

- [ ] **Step 3: Add one shared enabled guard**

Add to `cameras.py`:

```python
def _require_runtime_enabled(camera: Camera) -> None:
    if not camera.enabled:
        raise HTTPException(status_code=409, detail="camera is disabled")
```

Call it before opening any device stream in `preview_camera`, `start_camera`, and `restart_camera`. Keep `probe` unchanged.

For `start_camera`, use `start_regular_recorder(...)` rather than calling `recorder_manager.start(...)` directly so the event-buffer handoff invariant is preserved.

- [ ] **Step 4: Re-run guards and recorder handoff tests**

Run:

```bash
cd backend && uv run pytest \
  tests/test_camera_enabled_runtime_guard.py \
  tests/test_recorder_event_buffer_handoff.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/cameras.py backend/tests/test_camera_enabled_runtime_guard.py
git commit -m "fix: enforce disabled camera runtime guard"
```

---

### Task 5: Full slice verification and migration checklist update

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`
- Modify this plan only to mark completed checkboxes.

**Interfaces:**
- No new runtime interfaces.

- [ ] **Step 1: Run backend focused lifecycle suite**

Run:

```bash
cd backend && uv run pytest \
  tests/test_camera_runtime_coordinator.py \
  tests/test_camera_connection_write.py \
  tests/test_onvif_camera_api.py \
  tests/test_camera_enabled_runtime_guard.py \
  tests/test_camera_deletion.py \
  tests/test_event_recording_handoff.py \
  tests/test_recorder_event_buffer_handoff.py \
  tests/test_motion_manager.py \
  tests/test_recording_schedule.py -v
```

Expected: PASS.

- [ ] **Step 2: Run backend full suite and lint**

Run:

```bash
cd backend && uv run ruff check app tests migrations
cd backend && uv run pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run repository CI**

Require all backend pytest shards, backend quality/Ruff, frontend, Docker smoke, and migration compatibility to pass on the final head.

- [ ] **Step 4: Update migration checklist**

Mark the RuntimeCoordinator items complete only for recorder/schedule/motion/event lifecycle and disabled startup guards. Leave these items explicitly incomplete for later slices:

- active preview-session termination on disable/reload
- adapter-specific temporary session release, especially HIK bridge streams
- current-connection revision guards inside long-running worker reconnect loops
- adapter switching and unified frontend adapter API

- [ ] **Step 5: Commit documentation**

```bash
git add docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md \
  docs/superpowers/plans/2026-09-16-camera-runtime-coordinator.md
git commit -m "docs: record runtime coordinator completion"
```
