# Camera Connection Switch + ONVIF Persistence Implementation Plan

Status: **Complete — verified in CI #1182 (`35109383963`)**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CameraConnection` the canonical persisted/runtime connection source for manual RTSP and ONVIF cameras while keeping legacy `Camera` connection fields as rollback-compatible shadow fields.

**Architecture:** Extend the Phase 1 one-current-connection model with connection-scoped ONVIF config, then switch new manual RTSP writes and media resolution to that model. Existing dedicated ONVIF endpoints remain temporary wrappers, but they persist and resolve through `CameraConnection` rather than `Camera.onvif_metadata`; legacy Camera RTSP/auth fields continue to mirror the active connection for one rollback window.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-design.md` and `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`

## Global Constraints

- `camera.id` remains the stable monitoring-point identity; connection changes never create a replacement Camera.
- Every Camera has at most one current `CameraConnection`; this slice does not introduce candidate/fallback connections.
- Legacy `Camera.connection_type/ip/rtsp_port/username/password_encrypted/rtsp_path/sub_rtsp_path` remain as shadow fields for rollback compatibility.
- Current-connection fields win over legacy shadow fields whenever both are present and disagree.
- Existing production data is manual RTSP; do not backfill or infer ONVIF rows from legacy metadata during migration.
- Password ciphertext is never logged or copied into audit metadata.
- ONVIF-discovered stream URIs are stored without embedded credentials.
- Dedicated ONVIF API routes remain temporarily supported; unified adapter create/update APIs and adapter switching are later work.
- Runtime coordination remains on the existing managers in this slice; `CameraRuntimeCoordinator` is a separate lifecycle plan.
- HIK connection persistence is not changed in this slice.

---

### Task 1: Add connection-scoped ONVIF config model and migration

**Files:**
- Create: `backend/app/models/onvif_connection.py`
- Modify: `backend/app/models/camera_connection.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/20260916_0023_onvif_connection_config.py`
- Create: `backend/tests/test_onvif_connection_model.py`
- Create: `backend/tests/test_onvif_connection_migration.py`

**Interfaces:**
- Produces `OnvifConnectionConfig` keyed one-to-one by `connection_id`.
- Produces `CameraConnection.onvif_config` relationship.
- Migration creates only the new empty ONVIF config table; it must not backfill from `onvif_device_metadata` or modify existing manual RTSP connections.

- [x] **Step 1: Write failing ORM tests** that create `Camera -> CameraConnection(adapter="onvif") -> OnvifConnectionConfig`, round-trip device-service/profile/URI cache fields, and prove deleting the connection cascades only its config.
- [x] **Step 2: Write failing migration test** that upgrades a `20260916_0022` fixture containing a manual RTSP Camera/connection plus a legacy `onvif_device_metadata` row and asserts the new table exists but contains zero rows and the existing connection is unchanged.
- [x] **Step 3: Run** `cd backend && uv run pytest tests/test_onvif_connection_model.py tests/test_onvif_connection_migration.py -v`; RED was observed before implementation.
- [x] **Step 4: Implement `OnvifConnectionConfig`** with `connection_id`, `device_service_url`, `device_uuid`, capabilities/profile JSON caches, recording/preview/detection profile tokens, credential-free recording/preview/detection URI caches, and timestamps; add one-to-one relationship from `CameraConnection`.
- [x] **Step 5: Implement Alembic revision `20260916_0023`** creating/dropping only `onvif_connection_configs` and preserving every existing Camera/connection row byte-for-byte.
- [x] **Step 6: Re-run focused tests** and verify in CI.

### Task 2: Make manual RTSP create/update write the current connection

**Files:**
- Create: `backend/app/services/camera_connection.py`
- Modify: `backend/app/api/cameras.py`
- Create: `backend/tests/test_camera_connection_write.py`
- Modify: `backend/tests/test_camera_batch.py`

**Interfaces:**
- Produces `upsert_manual_rtsp_connection(camera, *, host, port, username, password_encrypted, main_path, sub_path, verification_status=None, verified_at=None, last_error=None) -> CameraConnection`.
- New manual RTSP Camera gets revision `1`; editing an existing manual RTSP connection updates the same connection row and increments `revision` when connection-scoped values actually change.
- The helper mirrors compatible values to the legacy Camera shadow fields in the same transaction.
- Calling it on a Camera whose current adapter is not `manual_rtsp` raises `ConnectionAdapterMismatch` rather than silently switching adapters.

- [x] **Step 1: Write failing service/API tests** proving `POST /api/cameras` creates one `CameraConnection(adapter="manual_rtsp")` plus `RtspConnectionConfig`, and that its ciphertext/endpoint match the legacy shadows.
- [x] **Step 2: Add failing update tests** proving changing RTSP host/path/auth preserves `camera.id`, preserves `connection.id`, increments revision, and updates both current connection and legacy shadows; semantically unchanged encrypted passwords do not increment revision.
- [x] **Step 3: Add failing batch test** proving every newly batch-created Camera receives exactly one RTSP current connection.
- [x] **Step 4: Run focused RED tests** for manual RTSP current-connection writes.
- [x] **Step 5: Implement the write helper** and route `_new_camera` plus manual RTSP update through it; keep encryption at the API boundary and compare encrypted-secret semantics safely.
- [x] **Step 6: Re-run focused tests** and verify in CI #1174.

### Task 3: Make media resolution prefer current connection state

**Files:**
- Modify: `backend/app/services/media_adapter.py`
- Modify: `backend/app/services/device_adapter.py`
- Modify: `backend/tests/test_media_adapter.py`
- Create: `backend/tests/test_manual_rtsp_connection_resolution.py`

**Interfaces:**
- `MediaAdapterRegistry.resolve(...)` selects `camera.connection.adapter` when a current connection exists; `camera.connection_type` is compatibility fallback only when it does not.
- `ManualRtspDeviceAdapter.resolve_media_source(...)` reads host/auth/port/main/sub from `CameraConnection + RtspConnectionConfig` when present; legacy Camera fields are compatibility fallback only.

- [x] **Step 1: Add failing registry test** with conflicting `camera.connection.adapter="manual_rtsp"` and legacy `camera.connection_type="hik_sdk"`; assert the current connection adapter wins.
- [x] **Step 2: Add failing RTSP resolution test** with conflicting current vs legacy host/credentials/paths; assert generated main/sub URIs use only current-connection values.
- [x] **Step 3: Keep a compatibility test** for lightweight/legacy Camera objects that have no `.connection`, proving existing unit-test and rollback behavior still resolves legacy RTSP fields.
- [x] **Step 4: Run focused RED tests** and observe legacy-selection failures.
- [x] **Step 5: Implement current-first adapter selection and RTSP resolution** without changing stream-role semantics.
- [x] **Step 6: Re-run focused media/preview/recorder tests** and verify full CI in #1178.

### Task 4: Persist ONVIF create/update through `CameraConnection`

**Files:**
- Modify: `backend/app/services/camera_connection.py`
- Modify: `backend/app/api/onvif_cameras.py`
- Modify: `backend/tests/test_onvif_camera_api.py`

**Interfaces:**
- Produces `upsert_onvif_connection(camera, *, host, username, password_encrypted, device_service_url, device_uuid, capabilities, profiles, recording_profile_token, preview_profile_token, detection_profile_token, recording_uri, preview_uri, detection_uri, verified_at) -> CameraConnection`.
- New ONVIF Camera gets `adapter="onvif"`, revision `1`, `verification_status="verified"`, and a populated `OnvifConnectionConfig`.
- Updating an ONVIF Camera preserves Camera/connection IDs and increments revision when connection-scoped state changes.
- Legacy Camera connection fields remain mirrored from the discovered RTSP stream for rollback/API compatibility; `OnvifDeviceMetadata` is no longer written for new/updated ONVIF cameras.

- [x] **Step 1: Change existing ONVIF API tests to RED** by asserting create persists `CameraConnection + OnvifConnectionConfig`, revision/status are correct, URI caches contain no credentials, and legacy `OnvifDeviceMetadata` is absent.
- [x] **Step 2: Add update assertions** that Camera ID and connection ID remain unchanged, revision advances, host/auth/config caches update, and current connection ciphertext decrypts to the new password.
- [x] **Step 3: Run focused RED tests** and observe missing current connection failures.
- [x] **Step 4: Extend the connection write service** with `upsert_onvif_connection`; reject an existing non-ONVIF adapter with `ConnectionAdapterMismatch` in this slice.
- [x] **Step 5: Refactor ONVIF create/update** to call the new helper after successful discovery/media validation, preserve existing media-capability cache updates and current recorder/motion/schedule behavior, and stop writing `OnvifDeviceMetadata`.
- [x] **Step 6: Re-run ONVIF API tests** as part of final CI #1182.

### Task 5: Make ONVIF runtime media resolution use connection-scoped config

**Files:**
- Modify: `backend/app/services/onvif_device_adapter.py`
- Modify: `backend/tests/test_media_adapter.py`
- Create: `backend/tests/test_onvif_connection_resolution.py`

**Interfaces:**
- `OnvifDeviceAdapter.resolve_media_source(...)` reads stream URI cache and credentials from `camera.connection.onvif_config` / `camera.connection` whenever a current connection exists.
- Legacy `camera.onvif_metadata` and Camera credentials are compatibility fallback only when there is no current connection.
- A current ONVIF connection missing its config is treated as invalid state and does not silently fall back to legacy metadata.
- Current config always wins if current and legacy values conflict.

- [x] **Step 1: Write failing resolution tests** with deliberately conflicting current config, legacy ONVIF metadata, and legacy Camera credentials; assert recording/preview/detection sources use the current config and current credentials.
- [x] **Step 2: Add fallback test** proving a legacy ONVIF Camera without any current connection still resolves through `OnvifDeviceMetadata` during the rollback window, while a current connection missing config raises an error.
- [x] **Step 3: Run focused RED tests** and observe legacy metadata/auth winning incorrectly.
- [x] **Step 4: Implement current-first ONVIF resolution** while preserving profile/stream-role selection and URI credential injection behavior.
- [x] **Step 5: Run ONVIF, media-input, motion/event-recording and preview coverage** through the complete backend CI shards.
- [x] **Step 6: Verify** current-first ONVIF runtime resolution in final CI #1182.

### Task 6: Verify the Switch slice and update migration status

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`
- Modify: `docs/superpowers/plans/2026-09-16-camera-connection-switch-onvif.md`
- Modify other files only if verification exposes defects.

**Interfaces:**
- Manual RTSP and ONVIF runtime media resolution are current-connection-first.
- Existing manual RTSP production rows upgrade from `0022 -> head` without value/history changes.
- New manual RTSP and ONVIF cameras always have exactly one current connection.

- [x] **Step 1: Run backend suite.** CI #1182 split the complete backend suite across four pytest shards; all four completed successfully.
- [x] **Step 2: Run lint.** CI #1182 `backend-quality` completed compileall, Ruff, HIK compile, and HIK tests successfully.
- [x] **Step 3: Run fresh-head and `0022 -> head` Alembic smoke tests**, preserving existing Camera IDs, manual RTSP connection IDs/config/ciphertext and history references while creating an empty ONVIF config table.
- [x] **Step 4: Run Docker smoke** through CI and verify backend health/database migration compatibility; CI #1182 `docker-smoke` completed successfully.
- [x] **Step 5: Update the migration checklist** to mark ONVIF config table creation, current-connection canonical RTSP/ONVIF reads/writes, rollback shadow writes, and dedicated ONVIF-wrapper persistence as complete; HIK, adapter switching, RuntimeCoordinator and Contract remain unchecked.
- [x] **Step 6: Mark this plan complete** after CI #1182 showed backend, frontend, Docker smoke and change classification all green.
