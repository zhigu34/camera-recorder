# Dashboard, Event Recording, and ONVIF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Dashboard activity startup so it opens at the latest state, add 5-second pre-roll event recording when normal recording is idle, and deliver the first usable ONVIF Device + Media integration.

**Architecture:** Keep Dashboard realtime updates but make REST queries return newest rows first so the websocket cursor starts at the database tail. Add an event-recording service that keeps bounded stream-copy ring segments only for enabled event detection cameras that are not already recording, then materializes `[event start - 5s, event end]` into a normal Recording row. Add an ONVIF adapter behind the existing Device Adapter / Stream Resolver boundary, persisting ONVIF-specific metadata separately from Camera and exposing probe/discovery APIs to the camera UI.

**Tech Stack:** FastAPI, SQLAlchemy async, FFmpeg/ffprobe, Vue 3 + TypeScript, pytest, Vitest, Alembic, ONVIF SOAP over httpx/zeep-compatible XML handling.

**Spec:** `docs/superpowers/specs/2026-09-15-event-detection-platform-design.md`

## Global Constraints

- Deployment remains exactly `git pull && ./deploy.sh`.
- Live and Playback must not auto-start media from navigation alone.
- Existing `manual_rtsp` cameras remain backward compatible.
- Event pre-roll is 5 seconds and is only needed when the regular recorder is not running.
- Event recording ends at the detector event end boundary.
- ONVIF implementation in this change covers Device + Media/Profile + Stream URI; WS-Discovery, native Events subscriptions, and PTZ control remain outside this delivery.
- High-risk media/backend changes require targeted regression coverage and PR CI before merge.

---

### Task 1: Dashboard starts from newest activity

**Files:**
- Modify: `backend/app/api/motion_detection.py`
- Modify: `backend/app/api/event_detection.py`
- Test: `backend/tests/test_motion_activity_api.py`
- Test: `backend/tests/test_event_detection_api.py`

**Interfaces:**
- Produces: `/api/motion-events` and `/api/detection-events` return newest matching rows first while preserving their existing response schemas.

- [ ] **Step 1: Write failing tests** that insert more rows than a small limit and assert the API returns the newest IDs in descending time/ID order.
- [ ] **Step 2: Run targeted pytest** and confirm the tests fail because current queries order ascending.
- [ ] **Step 3: Change both queries** to `order_by(started_at.desc(), id.desc())` before `limit`.
- [ ] **Step 4: Run targeted pytest** and confirm the new tests pass.

### Task 2: Event pre-roll recording service

**Files:**
- Create: `backend/app/services/event_recording.py`
- Modify: `backend/app/services/motion_manager.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_event_recording.py`
- Test: `backend/tests/test_motion_manager.py`

**Interfaces:**
- Produces: `event_recording_manager.reconcile_camera(camera_id)`, `event_recording_manager.capture(camera_id, started_at, ended_at) -> Recording | None`, and lifecycle `start()/stop()`.
- Consumes: `resolve_stream(camera, "recording")`, `recorder_manager.is_running(camera_id)`, configured FFmpeg/ffprobe binaries, and existing Recording persistence.

- [ ] **Step 1: Write failing unit tests** for clip window calculation, “do nothing while regular recorder is active”, bounded ring cleanup, and capture command construction using 5-second pre-roll.
- [ ] **Step 2: Run targeted pytest** and confirm missing service/behavior failures.
- [ ] **Step 3: Implement bounded per-camera stream-copy segment workers** using short MKV segments in a dedicated event buffer directory.
- [ ] **Step 4: Implement capture** that selects overlapping ring segments for `[started_at - 5s, ended_at]`, concat/remuxes into the normal recordings directory, probes media, creates a `Recording`, and leaves source ring segments intact until normal rotation cleanup.
- [ ] **Step 5: Integrate motion event persistence** so existing overlapping regular recordings win; otherwise request an event clip and store its `recording_id`.
- [ ] **Step 6: Start/stop the manager from application lifespan** after recorder/schedule startup and before motion detection.
- [ ] **Step 7: Run targeted pytest** and confirm service + motion integration pass.

### Task 3: ONVIF Device + Media adapter

**Files:**
- Create: `backend/app/models/onvif.py`
- Create: `backend/migrations/versions/20260915_0018_onvif_device_metadata.py`
- Create: `backend/app/services/onvif_client.py`
- Create: `backend/app/services/onvif_device_adapter.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/stream_resolver.py`
- Modify: `backend/app/schemas/camera.py`
- Modify: `backend/app/api/cameras.py`
- Modify: `frontend/src/CamerasView.vue`
- Modify: `frontend/src/stores/cameras.ts`
- Test: `backend/tests/test_onvif_client.py`
- Test: `backend/tests/test_stream_resolver.py`
- Test: `backend/tests/test_camera_connection_type.py`
- Test: `frontend/src/onvifCameraIntegration.test.ts`

**Interfaces:**
- Produces: ONVIF probe API that accepts host/port/username/password and returns device identity plus normalized media profiles; saved ONVIF cameras use `connection_type="onvif"`; resolver returns selected main/sub RTSP URI through the ONVIF adapter.
- Persists: one ONVIF metadata row per camera containing device service URL, device UUID, capability JSON, profile JSON, selected recording/preview/detection profile tokens, and credential-free stream URI templates.

- [ ] **Step 1: Write failing backend tests** using deterministic SOAP fixtures for Device Information, Capabilities, Profiles, and StreamUri normalization.
- [ ] **Step 2: Write failing resolver/schema tests** proving ONVIF creation is accepted only with validated ONVIF metadata and that purpose-based stream resolution maps recording to main and preview/detection to sub when available.
- [ ] **Step 3: Implement ONVIF SOAP client** with WS-Security UsernameToken digest, Device `GetDeviceInformation`, `GetCapabilities`, Media `GetProfiles`, and `GetStreamUri` calls; never persist credentials in returned URIs.
- [ ] **Step 4: Add metadata model + Alembic migration** with camera cascade delete.
- [ ] **Step 5: Add ONVIF probe/create/update API bridge** that stores normalized metadata and keeps Camera identity fields synchronized without overwriting explicit user form-factor choices.
- [ ] **Step 6: Register `OnvifDeviceAdapter` in Stream Resolver** and keep manual RTSP behavior unchanged.
- [ ] **Step 7: Add camera UI connection-type selector and ONVIF detect action**; ONVIF mode hides manual RTSP paths and fills manufacturer/model/profile summary from probe results.
- [ ] **Step 8: Run backend targeted tests, frontend tests, lint/typecheck/build**.

### Task 4: Integration verification and delivery

**Files:**
- Review all changed files in PR diff.
- Update documentation only if CI or review identifies a contract that is not already captured here.

- [ ] **Step 1: Open one PR to `main`.**
- [ ] **Step 2: Run PR CI once and inspect every failing job if any.**
- [ ] **Step 3: Review the full diff for credential leakage, unsafe path handling, unbounded event buffers, migration downgrade correctness, and accidental media auto-start.**
- [ ] **Step 4: If CI is green and review has no blocking issue, merge to `main`.**
- [ ] **Step 5: Deliver exactly the normal deployment command:** `git pull && ./deploy.sh`.
