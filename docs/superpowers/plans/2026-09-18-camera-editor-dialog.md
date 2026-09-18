# Camera Editor Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace separate RTSP, ONVIF, and HIK camera add/edit flows with one reusable adapter-aware CameraEditorDialog while preserving Camera identity/history and the Phase 5 split-view workspace.

**Architecture:** Keep the backend unified camera APIs unchanged. Introduce frontend camera/connection types plus a focused `CameraEditorDialog.vue` that loads `GET /api/camera-adapters`, renders adapter-specific fields, optionally probes connection drafts through `POST /api/camera-connections/probe`, and saves create/update through `POST /api/cameras` / `PUT /api/cameras/{id}`. `CamerasView.vue` owns selected camera data and opens the editor; `CamerasWorkspace.vue` drops legacy HIK/ONVIF add Teleports/modals but keeps batch add and detail extension content.

**Tech Stack:** Vue 3, TypeScript, Pinia, Vue Router, Element Plus, Axios, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-design.md` sections 11–16, especially section 14.

## Global Constraints

- One primary Add Camera action.
- Reuse the same editor for create, edit, and adapter switching.
- Adapter selector is driven by `GET /api/camera-adapters`.
- Unavailable adapters remain visible but disabled with the backend-provided reason.
- Adapter-specific connection fields replace only the connection section.
- Probe/discovery is optional; save must remain possible for offline/unverified connections.
- Cross-adapter edit must visibly summarize old -> new adapter and state that Camera ID/history remain unchanged.
- Preserve current Camera ID, deep link, preview/runtime operations, batch add, playback/recordings shortcuts, and event-detection shortcut.
- Do not implement Phase 5 PR3 history summary, deletion impact dialog, disable-confirmation redesign, or legacy backend contract cleanup.
- Do not change backend APIs, database models, migrations, or runtime services in this PR.

---

### Task 1: Lock the unified editor contract

**Files:**
- Create: `frontend/src/cameraEditorDialog.test.ts`
- Modify: `frontend/src/hikCameraIntegration.test.ts`
- Modify: `frontend/src/onvifCameraIntegration.test.ts`

**Interfaces:**
- Consumes: source of `CamerasView.vue`, `CamerasWorkspace.vue`, and future `CameraEditorDialog.vue`.
- Produces: source-contract checks requiring one primary editor, dynamic adapter registry, unified create/update APIs, optional probe, and removal of standalone HIK/ONVIF modals.

- [ ] Write RED tests that require:
  - `CameraEditorDialog` import/render from `CamerasView.vue`
  - `GET /api/camera-adapters`
  - `POST /api/camera-connections/probe`
  - `POST /api/cameras`
  - `PUT /api/cameras/${camera.id}`
  - adapter IDs `manual_rtsp`, `onvif`, `hik_sdk`
  - unavailable adapter reason rendering
  - switch copy that mentions Camera ID/history staying unchanged
  - `CamerasWorkspace.vue` no longer imports/renders `HikCameraAddView` or `OnvifCameraAddView`
  - no HIK/ONVIF heading Teleport buttons
- [ ] Open a draft PR to obtain CI RED evidence.
- [ ] Confirm the tests fail for missing unified-editor behavior, not syntax/config errors.
- [ ] Commit: `test: define unified camera editor contract`.

### Task 2: Add shared camera editor domain types and API mapping

**Files:**
- Create: `frontend/src/camera-editor/types.ts`
- Create: `frontend/src/camera-editor/model.ts`
- Test: `frontend/src/cameraEditorModel.test.ts`

**Interfaces:**
- Produces:
  - `CameraAdapterId = 'manual_rtsp' | 'onvif' | 'hik_sdk'`
  - `CameraAdapterCapability`
  - read/write connection unions matching backend schemas
  - editor draft type
  - `draftFromCamera(camera)`
  - `createPayloadFromDraft(draft)`
  - `updatePayloadFromDraft(camera, draft)`
  - `connectionFingerprint(draft)`

- [ ] Write model tests for all three adapters, create payloads, same-adapter edit, cross-adapter edit, password omission on same-adapter edit, and password requirement on create/switch.
- [ ] Implement minimal types/mappers.
- [ ] Verify targeted tests.
- [ ] Commit: `feat: add camera editor domain model`.

### Task 3: Build CameraEditorDialog

**Files:**
- Create: `frontend/src/CameraEditorDialog.vue`
- Create: `frontend/src/styles/camera-editor-dialog.css`
- Modify: `frontend/src/main.ts`
- Test: `frontend/src/cameraEditorDialog.test.ts`

**Interfaces:**
- Props:
  - `modelValue: boolean`
  - `camera: SharedCamera | null`
- Emits:
  - `update:modelValue`
  - `saved(cameraId: number)`
- Uses:
  - `GET /api/camera-adapters`
  - `POST /api/camera-connections/probe`
  - `POST /api/cameras`
  - `PUT /api/cameras/{id}`

- [ ] Load adapter capabilities on open.
- [ ] Render identity/device section.
- [ ] Render adapter selector from capability response; disable unavailable entries and surface reason.
- [ ] Render Manual RTSP fields: host, port, username, password, main path, sub path.
- [ ] Render ONVIF fields: host, port, username, password.
- [ ] Render HIK fields: host, SDK port, username, password, channel, main/sub stream type.
- [ ] Preserve optional probe semantics; successful probe can enrich manufacturer/model/name when empty, but failed/not-run probe does not block Save.
- [ ] On same-adapter edit, blank password means keep existing secret.
- [ ] On create or cross-adapter switch, password is required.
- [ ] Show old -> new adapter switch warning and Camera ID/history preservation copy.
- [ ] Render runtime policy fields currently owned by the legacy RTSP form: enabled, auto_record, timestamp_mode.
- [ ] Save using unified payloads and emit `saved`.
- [ ] Add responsive dialog styles.
- [ ] Verify editor contract/model tests.
- [ ] Commit: `feat: add unified camera editor dialog`.

### Task 4: Integrate editor into split-view camera page

**Files:**
- Modify: `frontend/src/CamerasView.vue`
- Modify: `frontend/src/stores/cameras.ts`
- Test: `frontend/src/cameraEditorDialog.test.ts`
- Test: `frontend/src/cameraSplitView.test.ts`

**Interfaces:**
- `CamerasView.vue` opens editor with `camera=null` for Add and selected camera for Edit.
- Camera store read model includes canonical `connection` from `CameraRead`.
- After save, invalidate/reload and retain/select saved Camera ID.

- [ ] Extend `SharedCamera` with canonical `connection` read data.
- [ ] Remove legacy RTSP form state/functions/dialog from `CamerasView.vue`.
- [ ] Wire the existing Add Camera CTA to `CameraEditorDialog`.
- [ ] Wire detail Edit action to the same dialog.
- [ ] After save, refresh store and deep-link/select the saved Camera ID.
- [ ] Preserve preview/runtime/split-view behavior.
- [ ] Verify split-view/editor tests.
- [ ] Commit: `refactor: use unified editor in camera workspace`.

### Task 5: Remove standalone HIK/ONVIF add flows from the workspace

**Files:**
- Modify: `frontend/src/CamerasWorkspace.vue`
- Modify: `frontend/src/hikCameraIntegration.test.ts`
- Modify: `frontend/src/onvifCameraIntegration.test.ts`

**Interfaces:**
- Keeps batch-add dialog and detail Teleports.
- Removes HIK/ONVIF imports, state, heading Teleport buttons, and standalone dialogs.

- [ ] Delete HIK/ONVIF workspace modal state/handlers/imports.
- [ ] Remove adapter heading Teleport and MutationObserver dependency that existed only for those buttons; retain detail extension target tracking.
- [ ] Keep `BatchCamerasView`, playback, recordings, and event detection unchanged.
- [ ] Update legacy integration tests to assert the old standalone entrypoints are absent and the unified editor contains the corresponding adapter path.
- [ ] Verify targeted tests.
- [ ] Commit: `refactor: retire standalone camera adapter modals`.

### Task 6: Full frontend verification and PR gate

**Files:** no product changes unless verification exposes a regression.

- [ ] Run frontend lint, full Vitest suite, and production build in CI.
- [ ] Confirm backend/docker jobs are success or correctly skipped because PR2 is frontend-only.
- [ ] Review diff for no backend/API/DB changes.
- [ ] Confirm exact-head CI green.
- [ ] Update PR description from RED baseline to implemented scope.
- [ ] Mark ready only after exact-head green.
