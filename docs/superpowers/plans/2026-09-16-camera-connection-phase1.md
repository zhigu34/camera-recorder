# Camera Connection Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a safe current-connection domain model for existing RTSP cameras while preserving every `camera.id` and all historical records, and make permanent deletion refuse cameras with meaningful history.

**Architecture:** Keep `Camera` as the stable monitoring-point identity and add one `CameraConnection` per Camera plus adapter-specific RTSP config. Existing production data is RTSP-only, so the migration backfills exactly one RTSP connection per Camera and aborts if legacy non-RTSP rows are encountered. Historical Camera foreign keys become restrictive rather than cascading, while current configuration remains deletable with an empty/test Camera.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-design.md` and `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`

## Global Constraints

- `camera.id` is never renumbered or recreated during migration.
- Existing recordings/events/motion events/health samples keep their original `camera_id`.
- Existing encrypted passwords are copied byte-for-byte; never decrypt/re-encrypt during migration.
- Production data is expected to be `manual_rtsp`; migration must abort on any unexpected legacy adapter instead of guessing.
- No user-facing cascade-delete-history operation is introduced.
- Legacy Camera connection columns remain during Phase 1 for rollback compatibility.

---

### Task 1: Add current connection ORM models

**Files:**
- Create: `backend/app/models/camera_connection.py`
- Modify: `backend/app/models/camera.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_camera_connection_model.py`

**Interfaces:**
- Produces `CameraConnection` with one-to-one `camera_id`, `adapter`, `host`, credentials, revision and verification state.
- Produces `RtspConnectionConfig` keyed one-to-one by `connection_id`.
- Produces `Camera.connection` relationship.

- [ ] **Step 1: Write failing model tests** asserting one Camera can own exactly one current connection, RTSP config fields round-trip, and default revision/status are `1` / `unverified`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_camera_connection_model.py -v`; expect failure because the models do not exist.
- [ ] **Step 3: Implement minimal ORM models and exports.**
- [ ] **Step 4: Re-run the focused test and then** `cd backend && uv run pytest tests/test_camera_connection_model.py tests/test_camera_connection_type.py -v`.
- [ ] **Step 5: Commit** `feat: add camera current connection models`.

### Task 2: Add RTSP-only data migration and guard unexpected adapters

**Files:**
- Create: `backend/migrations/versions/20260916_0020_camera_connections.py`
- Test: `backend/tests/test_camera_connection_migration.py`

**Interfaces:**
- Migration creates `camera_connections` and `rtsp_connection_configs`.
- Backfill maps legacy Camera fields to exactly one RTSP connection without changing Camera IDs.
- Migration raises a clear exception containing offending Camera IDs if `connection_type != manual_rtsp` exists.

- [ ] **Step 1: Write failing migration tests** using a temporary SQLite database upgraded through `20260916_0019`, insert representative legacy Camera rows, upgrade to `20260916_0020`, and assert IDs/connection fields/password ciphertext are unchanged.
- [ ] **Step 2: Add a failing test** inserting a legacy non-RTSP Camera and assert upgrade to `0020` aborts with its Camera ID.
- [ ] **Step 3: Run** `cd backend && uv run pytest tests/test_camera_connection_migration.py -v`; expect failure because revision `0020` is absent.
- [ ] **Step 4: Implement migration** with schema creation, strict preflight guard, RTSP backfill, uniqueness constraints, and downgrade that drops only new connection tables.
- [ ] **Step 5: Re-run focused migration tests.**
- [ ] **Step 6: Commit** `feat: migrate legacy RTSP cameras to current connections`.

### Task 3: Protect camera history from cascade deletion

**Files:**
- Create: `backend/migrations/versions/20260916_0021_protect_camera_history.py`
- Modify: `backend/app/models/recording.py`
- Modify: `backend/app/models/motion.py`
- Modify: `backend/app/models/health_sample.py`
- Modify: `backend/app/models/camera.py`
- Test: `backend/tests/test_camera_history_fk.py`

**Interfaces:**
- `recordings.camera_id`, `motion_events.camera_id`, and `camera_health_samples.camera_id` use restrictive/no-action Camera foreign keys.
- ORM relationship from Camera to recordings must not use delete-orphan/cascade semantics that silently delete history.

- [ ] **Step 1: Write failing integration tests** that create Camera + Recording / MotionEvent / HealthSample and assert deleting Camera raises an integrity failure while historical rows remain.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_camera_history_fk.py -v`; verify current cascade behavior makes the test fail.
- [ ] **Step 3: Implement SQLite-safe Alembic table rebuilds/batch alters and ORM relationship changes.**
- [ ] **Step 4: Re-run focused tests and migration upgrade/downgrade smoke tests.**
- [ ] **Step 5: Commit** `fix: protect camera history from cascade deletion`.

### Task 4: Classify Event deletion blockers explicitly

**Files:**
- Create: `backend/migrations/versions/20260916_0022_event_delete_blocking.py`
- Modify: `backend/app/models/event.py`
- Modify: `backend/app/services/event_log.py`
- Test: `backend/tests/test_event_delete_blocking.py`

**Interfaces:**
- `Event.blocks_camera_delete: bool` defaults according to explicit event creation intent.
- `add_event(..., blocks_camera_delete=False)` and `add_audit_event(...)` are non-blocking by default.
- Business/monitoring event producers that should preserve Camera history set the flag explicitly.

- [ ] **Step 1: Write failing tests** proving audit/lifecycle events do not block deletion and explicitly marked business events do.
- [ ] **Step 2: Run focused test; expect missing field/signature failure.**
- [ ] **Step 3: Add model/migration/service parameter and conservative backfill for existing rows (`recording_id IS NOT NULL` or monitoring-event categories become blocking; audit/lifecycle stay non-blocking).**
- [ ] **Step 4: Update existing event producers only where business-history semantics are clear.**
- [ ] **Step 5: Run event-related test suite.**
- [ ] **Step 6: Commit** `feat: classify camera history events for deletion`.

### Task 5: Add deletion-impact service and safe DELETE behavior

**Files:**
- Create: `backend/app/services/camera_deletion.py`
- Modify: `backend/app/api/cameras.py`
- Modify: `backend/app/schemas/camera.py`
- Test: `backend/tests/test_camera_deletion.py`

**Interfaces:**
- `camera_deletion_impact(db, camera_id) -> CameraDeletionImpact` returns counts for recordings, motion events, health samples, blocking business events and pending uploads.
- `GET /api/cameras/{camera_id}/deletion-impact` returns structured counts.
- `DELETE /api/cameras/{camera_id}` returns HTTP 409 with the same structured blocker information when history exists; otherwise stops runtime state and permanently deletes the empty/test Camera and current config.

- [ ] **Step 1: Write failing service/API tests** for empty Camera deletion, recorded Camera refusal, health-only refusal, and non-blocking audit events not preventing deletion.
- [ ] **Step 2: Run focused tests; verify current DELETE behavior fails them.**
- [ ] **Step 3: Implement deletion-impact schema/service and endpoint.**
- [ ] **Step 4: Refactor DELETE to call the impact service before any destructive ORM operation.**
- [ ] **Step 5: Run** `cd backend && uv run pytest tests/test_camera_deletion.py tests/test_camera_history_fk.py tests/test_event_delete_blocking.py -v`.
- [ ] **Step 6: Commit** `feat: guard camera deletion with history impact`.

### Task 6: Phase 1 verification

**Files:**
- Modify only if verification exposes defects.

- [ ] **Step 1: Run backend suite:** `cd backend && uv run pytest -q`.
- [ ] **Step 2: Run lint:** `cd backend && uv run ruff check app tests migrations`.
- [ ] **Step 3: Run Alembic head smoke upgrade on a fresh SQLite database and an upgrade from revision `20260916_0019` populated with RTSP fixtures.**
- [ ] **Step 4: Verify migration invariants:** same Camera count/IDs; same Recording/MotionEvent/HealthSample counts and `camera_id`; identical password ciphertext; one current connection per Camera.
- [ ] **Step 5: Update the design/migration checklist with completed Phase 1 items.**
- [ ] **Step 6: Commit verification/doc fixes if needed and open a PR for Phase 1 review.**
