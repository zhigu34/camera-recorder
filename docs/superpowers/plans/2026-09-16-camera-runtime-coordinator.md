# Camera Runtime Coordinator Implementation Plan

Status: **Complete — production code verified in CI #1204 (`35119089053`)**

**Goal:** Centralize per-camera recorder, schedule, motion, and event-buffer lifecycle so connection edits and enable/disable changes no longer coordinate runtime workers independently in API handlers.

**Architecture:** `CameraRuntimeCoordinator` is the per-camera stop/reload orchestration layer for the existing recorder, recording-schedule, event-recording, and motion managers. It snapshots recorder ownership, stops workers in a deterministic order, reloads the committed Camera/current connection, leaves disabled cameras fully stopped, restores manual or schedule-owned recording policy, then restores event buffering before motion detection.

**Spec:** `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-design.md`

## Global constraints

- `Camera.id` remains the stable monitoring-point identity.
- `Camera.enabled=false` is the authoritative runtime master switch.
- Connection edits persist before runtime reload and are not rolled back by a later runtime failure.
- A previously manual-running recorder can be restored after a connection-only reload.
- Schedule-owned recording is restored through schedule reconciliation.
- Event pre-roll ownership is cleared during teardown and event buffering is restored before motion detection.
- This slice coordinates existing managers; it does not implement HIK persistence, adapter switching, active preview-session termination, HIK temporary-session release, or connection-revision stale-worker guards.

## Completed implementation

### Task 1 — Expose recording ownership

- [x] Add `RecordingScheduleManager.recording_owner(camera_id)`.
- [x] Add `RecordingScheduleManager.detach_for_runtime_reload(camera_id)` without treating coordinator stops as user pauses.
- [x] RED verified in CI #1191: the new ownership methods were absent.
- [x] GREEN verified in CI #1192.

### Task 2 — Add `CameraRuntimeCoordinator`

- [x] Add `RuntimeStopSnapshot(was_recording, recording_owner)`.
- [x] Add `stop_all(camera_id, forget_schedule=False)`.
- [x] Stop motion, clear active event ownership, stop event buffering, stop recorder if running, then detach or forget schedule runtime state.
- [x] Add `reload(camera_id, schedule_changed=False)` returning `missing`, `disabled`, or `running`.
- [x] Restore manual recording through `start_regular_recorder` when appropriate.
- [x] Restore schedule-owned policy through schedule reconciliation.
- [x] Restore event buffering before motion detection.
- [x] RED verified in CI #1195: coordinator module did not exist.
- [x] GREEN verified in CI #1197.

### Task 3 — Route Camera and ONVIF lifecycle edits through the coordinator

- [x] Manual RTSP connection changes call one coordinator reload after commit.
- [x] Manual RTSP runtime-policy changes call coordinator reload with `schedule_changed=True`.
- [x] Metadata-only manual RTSP changes do not reload runtime.
- [x] ONVIF re-discovery/update commits first, then calls one coordinator reload.
- [x] Camera DELETE calls `stop_all(..., forget_schedule=True)` before deleting the Camera.
- [x] Remove API-level direct recorder/motion/event/schedule coordination from those lifecycle paths.
- [x] RED verified in CI #1198: all three new API coordination cases failed because the coordinator was not called.
- [x] GREEN behavior re-verified in CI #1202 across all four backend shards, quality, frontend, and Docker smoke checks.

### Task 4 — Enforce `Camera.enabled` on device-access entry points

- [x] Add one shared `_require_runtime_enabled(camera)` guard.
- [x] Disabled Camera returns HTTP 409 from manual start.
- [x] Disabled Camera returns HTTP 409 from restart.
- [x] Disabled Camera returns HTTP 409 before opening a new MJPEG preview.
- [x] Explicit one-shot Probe remains allowed while disabled.
- [x] Manual start uses `start_regular_recorder(...)` so regular recording correctly takes ownership from the event pre-roll buffer.
- [x] RED verified in CI #1203: disabled start returned 200 and manual start bypassed the handoff entrypoint.
- [x] GREEN verified in CI #1204.

### Task 5 — Full verification and migration checklist

- [x] All four backend pytest shards pass on production-code head `465dc765a2c5807103d6aeab2df6b4ca2c74ed5e`.
- [x] Backend compile/Ruff and HIK bridge tests pass.
- [x] Frontend lint/tests/build pass.
- [x] Docker smoke, health/proxy checks, and Alembic migration compatibility pass.
- [x] Aggregate backend job passes.
- [x] Migration checklist records only the lifecycle and disabled-runtime capabilities actually completed by this slice.
- [x] Follow-up lifecycle work remains explicitly listed below.

## Verification record

Final production-code verification before documentation-only closure:

- CI: **#1204**
- Run: `35119089053`
- Head: `465dc765a2c5807103d6aeab2df6b4ca2c74ed5e`
- Result: all required jobs passed.

A final CI run on the documentation-complete PR head is required before merge.

## Explicit follow-up work

- [ ] Terminate already-active preview sessions when disable/reload occurs.
- [ ] Release adapter-specific temporary sessions on disable/reload, especially HIK bridge streams.
- [ ] Add current-connection revision guards inside long-running worker reconnect loops so stale workers self-terminate.
- [ ] Migrate HIK persistence/runtime state into the current connection model.
- [ ] Add adapter switching while preserving the same `Camera.id`.
- [ ] Introduce the unified frontend adapter API and remove legacy adapter-specific UI/routes during the later Contract phase.
