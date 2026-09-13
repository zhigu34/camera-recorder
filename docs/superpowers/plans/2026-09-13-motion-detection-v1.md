# Motion Detection V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add low-cost motion detection with optional polygon zones, persisted motion events and snapshots, camera-level configuration, and Playback V3 timeline integration without changing the existing recording path.

**Architecture:** Recording remains on the existing main-stream FFmpeg path. A separate per-camera motion worker reads the preferred substream (falling back to main), FFmpeg emits low-rate scaled BGR frames, OpenCV performs MOG2-based motion analysis, and a small event state machine persists confirmed events. Configuration, zones, and motion events live in dedicated tables and APIs; Playback consumes motion events by time range.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite, FFmpeg, NumPy, opencv-python-headless, Vue 3, TypeScript, Element Plus.

**Spec:** `docs/superpowers/specs/2026-09-13-motion-detection-v1-design.md`

## Global Constraints

- Recording main-stream behavior must not change.
- Prefer `sub_rtsp_path`; fall back to the existing main RTSP path.
- Zone coordinates are normalized floats in `[0, 1]`; no enabled zones means full-frame detection.
- V1 detects motion only; no person/vehicle AI, tracking, face recognition, or LPR.
- Motion events are stored separately from existing operational `events`.
- One motion worker maximum per camera; failures are isolated and workers back off on reconnect.
- Defaults: sensitivity `medium`, 5 FPS, width 640, minimum duration 800 ms, merge gap 3000 ms.

---

### Task 1: Persistence and API contracts

**Files:**
- Create: `backend/app/models/motion.py`
- Create: `backend/app/schemas/motion.py`
- Create: `backend/migrations/versions/20260913_0013_motion_detection.py`
- Create: `backend/tests/test_motion_models.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Produces SQLAlchemy models `MotionDetectionSettings`, `MotionZone`, `MotionEvent`.
- Produces Pydantic contracts for settings updates, zone CRUD, runtime state, and event responses.

- [ ] Write failing tests for polygon validation, setting bounds/defaults, and event time fields.
- [ ] Run backend CI and verify tests fail because motion schemas/models are missing.
- [ ] Implement models, schemas, exports, and migration.
- [ ] Run backend CI and verify tests pass.

### Task 2: Motion geometry and event state machine

**Files:**
- Create: `backend/app/services/motion_detection.py`
- Create: `backend/tests/test_motion_detection.py`

**Interfaces:**
- Produces `sensitivity_profile(level)`.
- Produces normalized polygon/zone hit helpers.
- Produces `MotionEventStateMachine` that confirms after `min_duration_ms` and closes after `merge_gap_ms`.

- [ ] Write failing tests for full-frame behavior, zone hits, sensitivity profiles, duration threshold, and merge-gap behavior.
- [ ] Verify red in CI.
- [ ] Implement the smallest pure-Python/NumPy logic required by tests.
- [ ] Verify green in CI.

### Task 3: Motion configuration and event APIs

**Files:**
- Create: `backend/app/api/motion_detection.py`
- Create: `backend/tests/test_motion_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- `GET/PUT /api/cameras/{camera_id}/motion-detection`
- `POST/PUT/DELETE /api/cameras/{camera_id}/motion-zones...`
- `GET /api/motion-events`
- `GET /api/motion-events/{event_id}/snapshot`

- [ ] Write failing CRUD/isolation/time-overlap tests.
- [ ] Verify red in CI.
- [ ] Implement endpoints with camera ownership checks and normalized API responses.
- [ ] Verify green in CI.

### Task 4: FFmpeg frame worker and manager

**Files:**
- Create: `backend/app/services/motion_worker.py`
- Create: `backend/app/services/motion_manager.py`
- Create: `backend/tests/test_motion_worker.py`
- Modify: `backend/app/main.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- `build_motion_command(...) -> list[str]`.
- `MotionDetectionManager.start()`, `.stop()`, `.restart_camera(camera_id)`, `.stop_camera(camera_id)`, `.status(camera_id)`.

- [ ] Write failing command/lifecycle/restart tests.
- [ ] Verify red in CI.
- [ ] Add NumPy/OpenCV dependencies and implement low-rate FFmpeg BGR worker plus manager/backoff.
- [ ] Persist confirmed events and best-frame JPEG snapshots without blocking recorder processes.
- [ ] Start/stop manager from FastAPI lifespan.
- [ ] Verify all backend and Docker smoke CI.

### Task 5: Camera motion settings and polygon editor

**Files:**
- Create: `frontend/src/MotionZoneEditor.vue`
- Create: `frontend/src/utils/motionZones.ts`
- Create: `frontend/src/motionZones.test.ts`
- Modify: `frontend/src/CamerasView.vue`
- Modify: `frontend/src/styles/camera-detail-drawer.css`

**Interfaces:**
- Camera drawer can read/update motion settings and CRUD polygon zones.
- Zone editor converts between canvas pixels and normalized coordinates.

- [ ] Write failing conversion tests.
- [ ] Verify red in frontend CI.
- [ ] Implement motion settings section, runtime states, zone list, and snapshot-backed polygon editor.
- [ ] Verify frontend tests/build.

### Task 6: Playback V3 motion timeline

**Files:**
- Modify: `frontend/src/RecordingManagementView.vue`
- Modify: `frontend/src/styles/recording-management.css`
- Create/modify playback utility tests as needed.

**Interfaces:**
- Load motion events for current camera/date viewport.
- Render a real `移动` track; no person/vehicle placeholders.
- Clicking an event seeks to `started_at - 2s`; hover shows zone, time range, and duration.

- [ ] Write failing time-position/seek tests.
- [ ] Verify red in frontend CI.
- [ ] Implement event fetch, track rendering, zoom-aware positioning, and click-to-seek.
- [ ] Verify frontend tests/build and full CI.

### Task 7: Deployment verification

**Files:**
- Modify deployment files only if dependency installation requires it.

- [ ] Confirm migration runs automatically through existing startup flow.
- [ ] Confirm `docker compose build backend frontend` succeeds.
- [ ] Confirm `/health` stays healthy with motion detection disabled by default.
- [ ] Confirm enabling one camera starts only its motion worker and disabling stops it.
- [ ] Confirm recorder state and current recording behavior are unchanged.
