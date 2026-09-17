# HIK Canonical Connection + Adapter Switching Implementation Plan

**Goal:** Move Hikvision persistence/runtime reads to `CameraConnection + HikConnectionConfig` and add explicit backend switching among `manual_rtsp`, `onvif`, and `hik_sdk` without changing `camera.id` or historical ownership.

**Architecture:** Keep ordinary adapter upserts strict. Add a HIK canonical config model and an explicit switch primitive that replaces only adapter-specific config on the existing `CameraConnection`, increments revision once, mirrors rollback fields, and lets API boundaries validate target adapters before persistence. Reuse `CameraRuntimeCoordinator` through a new restore phase so switch orchestration can stop once, persist transactionally, then restore the pre-switch runtime owner.

**Tech stack:** FastAPI, SQLAlchemy async ORM, Alembic, SQLite, pytest, GitHub Actions.

---

## Task 1: HIK canonical config table and ORM relationship

**Files:**
- Create: `backend/migrations/versions/20260917_0024_hik_connection_config.py`
- Modify: `backend/app/models/hikvision.py`
- Modify: `backend/app/models/camera_connection.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_hik_connection_migration.py`
- Create: `backend/tests/test_hik_connection_model.py`

**TDD cycle:**
1. Add tests proving migration `0024` creates an empty `hik_connection_configs` table while leaving legacy `hik_device_metadata` and existing connection rows untouched.
2. Add ORM tests proving `HikConnectionConfig.connection_id` is the one-to-one PK/FK and `CameraConnection.hik_config` owns it with delete-orphan semantics.
3. Run PR CI and confirm RED because the table/model do not exist.
4. Add the migration and ORM model/relationship/export only.
5. Re-run CI and confirm the new migration/model tests pass.

The migration is Expand-only. Do not backfill historical HIK metadata.

## Task 2: Strict HIK upsert and current-first runtime resolution

**Files:**
- Modify: `backend/app/services/camera_connection.py`
- Modify: `backend/app/services/hik_media_proxy.py`
- Modify: `backend/app/services/hik_media_adapter.py`
- Modify: `backend/tests/test_hik_camera_api.py`
- Modify: `backend/tests/test_hik_media_proxy.py`
- Modify: `backend/tests/test_hik_media_adapter.py`
- Create: `backend/tests/test_hik_connection_write.py`

**TDD cycle:**
1. Add tests for `upsert_hik_connection()` creation, same-adapter update, same-plaintext-password stability, revision increments, mismatch rejection, and rollback shadow writes.
2. Add current-first runtime tests: canonical connection wins over legacy metadata; canonical `hik_sdk` without `hik_config` is corruption and must not fall back; legacy fallback is allowed only when `camera.connection is None`.
3. Add API creation/update assertions that HIK writes a canonical current connection/config while keeping `HikDeviceMetadata` as a shadow.
4. Confirm RED in PR CI.
5. Implement the strict HIK upsert and switch HIK media resolution to current-first semantics.
6. Confirm GREEN.

New HIK cameras must always create a current connection. Updating a legacy HIK camera with no connection upgrades it to canonical storage.

## Task 3: Explicit adapter switch primitive

**Files:**
- Modify: `backend/app/services/camera_connection.py`
- Create: `backend/tests/test_camera_connection_switch.py`

**TDD cycle:**
1. Add tests for `manual_rtsp -> onvif`, `onvif -> hik_sdk`, and `hik_sdk -> manual_rtsp` using one camera.
2. Assert `camera.id` and existing `camera.connection.id` remain unchanged, revision increments exactly once per switch, stale adapter configs are removed, only the target config remains, rollback shadows match the target, and history FKs remain attached to the same camera.
3. Confirm RED.
4. Add explicit switch helpers/primitive; do not relax strict ordinary upserts.
5. Confirm GREEN.

Switch implementation must mutate the existing `CameraConnection` object when present. It must explicitly clear old `rtsp_config`, `onvif_config`, and `hik_config` relationships before attaching the target config so delete-orphan removes stale rows.

## Task 4: Runtime stop/restore semantics for switching

**Files:**
- Modify: `backend/app/services/camera_runtime_coordinator.py`
- Modify: `backend/tests/test_camera_runtime_coordinator.py`
- Create/Modify: `backend/tests/test_camera_connection_switch.py`

**TDD cycle:**
1. Add tests proving `restore(camera_id, snapshot, schedule_changed=False)` restores manual recording ownership or schedule reconciliation without calling `stop_all()` again.
2. Add orchestration tests proving persistence failure can restore the old runtime after rollback, while runtime restore failure after successful persistence leaves the new connection persisted and surfaces the error.
3. Confirm RED.
4. Extract `restore()` from the current reload tail and make `reload()` call `stop_all()` then `restore()`.
5. Add a small switch orchestration helper if needed; keep database transaction ownership at the API/service boundary.
6. Confirm GREEN.

Do not add active preview HTTP/HIK bridge session termination in this slice.

## Task 5: Wire existing adapter APIs to explicit switching

**Files:**
- Modify: `backend/app/api/cameras.py`
- Modify: `backend/app/api/onvif_cameras.py`
- Modify: `backend/app/api/hik_cameras.py`
- Modify: `backend/tests/test_camera_connection_write.py`
- Modify: `backend/tests/test_onvif_camera_api.py`
- Modify: `backend/tests/test_hik_camera_api.py`
- Create: `backend/tests/test_camera_adapter_switch_api.py`

**TDD cycle:**
1. Add API tests proving target validation/probe happens before persistence and validation failure leaves the old adapter/config untouched.
2. Add cross-adapter endpoint tests for the three target endpoints. Same-adapter updates must still call strict upserts; mismatches must enter the explicit switch path.
3. For `PUT /api/cameras/{id}` switching from a non-RTSP adapter to manual RTSP, require complete target connection input (`ip`, `rtsp_port`, `username`, `password`, `rtsp_path`; `sub_rtsp_path` optional). Do not derive missing target parameters from the old ONVIF/HIK adapter.
4. Confirm RED.
5. Wire endpoints after successful target validation. Stop runtime before switch persistence, commit once, then restore from the captured snapshot. On DB failure: rollback, restore old runtime, re-raise mapped API error. On post-commit restore failure: keep new persisted connection and return/surface runtime failure; never silently revert.
6. Confirm GREEN.

## Task 6: Migration status/docs and verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`
- Optionally modify: `docs/HIK_SDK_RUNTIME.md` if runtime source-of-truth wording is stale.

**Verification:**
1. Run the full backend CI matrix through the PR.
2. Check migration upgrade path through `20260917_0024` and downgrade of the new table.
3. Run whitespace/diff checks from CI.
4. Review the PR diff for secrets, accidental frontend scope, legacy-field removal, or preview-session lifecycle scope creep.
5. Update the migration checklist only for items actually completed by this PR: HIK connection-config table, HIK canonical persistence/runtime reads, new HIK connections in the new model, three-way backend adapter switching, and HIK routes as wrappers over current connection service.

**Out of scope:** unified frontend connection switch UI, active preview/session termination, HIK bridge central session registry, destructive legacy-column removal, shadow-write removal, old adapter route deletion.