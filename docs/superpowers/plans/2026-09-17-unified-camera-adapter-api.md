# Unified Camera Adapter API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Camera Architecture Refactor Phase 3 by exposing one adapter-aware camera API for manual RTSP, ONVIF, and HIK SDK while preserving stable Camera identity, current connection identity, revision semantics, optional probe, offline/unverified saves, and the already-verified RuntimeCoordinator switch transaction semantics.

**Architecture:** Add a discriminated connection draft/read contract, an adapter capability/probe service, and one camera mutation service that delegates to the existing strict upsert/switch primitives. Existing `/api/cameras/onvif`, `/api/cameras/hik`, and legacy flat manual RTSP requests remain compatibility wrappers during the Switch window; new frontend code uses the unified `/api/cameras`, `/api/camera-adapters`, and `/api/camera-connections/probe` contract. Cross-adapter persistence continues to use `stop_all -> transaction -> restore`; commit failure restores the old runtime, while a post-commit restore failure does not revert the newly persisted connection.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async ORM, Alembic/SQLite, pytest, existing CameraRuntimeCoordinator and camera_connection services.

**Spec:** `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-design.md` (Phase 3 — Unified adapter API), plus the already-approved switch transaction semantics in `docs/superpowers/specs/2026-09-17-hik-connection-switching-design.md`.

## Global Constraints

- `Camera.id` is the stable monitoring-point identity and never changes for adapter edits/switches.
- Preserve the existing `CameraConnection.id` when switching adapters.
- Increment `CameraConnection.revision` exactly once for a real connection change; do not increment for metadata-only changes or no-op connection payloads.
- Connection test/discovery is optional. Structurally valid manual RTSP, ONVIF, and HIK connection drafts may be saved while offline.
- Saved-but-not-successfully-probed connections use `verification_status="unverified"`; explicit persisted probe failure uses `failed`; successful persisted probe uses `verified`.
- Do not retain plaintext credentials or credential-bearing ONVIF URI caches.
- Current `CameraConnection + adapter config` remains canonical. Legacy Camera fields and legacy adapter metadata stay rollback shadows for the compatibility window.
- Existing dedicated ONVIF/HIK routes remain temporary wrappers; they must not become a second persistence implementation.
- Adapter-specific discovery/probe code lives in services, not in frontend-facing route modules.
- Cross-adapter mutation preserves the proven lifecycle: validate payload before teardown; `stop_all`; persist/commit; `restore`; rollback + restore old runtime on persistence failure; never silently roll back a successfully committed new connection because restore failed.
- Invalid schedules/structural payloads must fail before `stop_all`.
- Phase 3 does not remove legacy fields/routes and does not implement Phase 4 optional HIK deployment or Phase 5 split-view UI.

---

### Task 1: Allow canonical ONVIF/HIK connections to exist before successful probe

**Files:**
- Create: `backend/migrations/versions/20260917_0025_onvif_unverified_connection.py`
- Modify: `backend/app/models/onvif_connection.py`
- Modify: `backend/app/services/camera_connection.py`
- Test: `backend/tests/test_camera_connection_write.py`
- Test: `backend/tests/test_camera_connection_migration.py`
- Create: `backend/tests/test_unverified_adapter_connection.py`

**Interfaces:**
- Produces: `upsert_onvif_connection(..., verification_status: str = "unverified", verified_at: datetime | None = None, last_error: str | None = None, device_uuid: str | None = None, capabilities: dict | None = None, profiles: list[dict] | None = None, recording_profile_token: str | None = None, preview_profile_token: str | None = None, detection_profile_token: str | None = None, recording_uri: str | None = None, preview_uri: str | None = None, detection_uri: str | None = None) -> CameraConnection`
- Produces: `upsert_hik_connection(..., verification_status: str = "unverified", verified_at: datetime | None = None, last_error: str | None = None, device_serial: str | None = None, device_model: str | None = None, device_name: str | None = None) -> CameraConnection`
- Preserves existing `switch_to_*_connection` identity/revision behavior.

- [ ] **Step 1: Write RED tests for unverified ONVIF/HIK persistence**

Add tests proving an ONVIF connection can be created with only host/username/password/device service URL and null discovery cache, and a HIK connection can be created with host/username/password/sdk_port/channel without discovered serial/model/name. Assert `verification_status == "unverified"`, `verified_at is None`, adapter config rows exist, and legacy rollback shadows are still written.

```python
def test_onvif_connection_can_be_saved_unverified_without_discovery_cache():
    camera = make_camera()
    connection = upsert_onvif_connection(
        camera,
        host="192.0.2.20",
        username="admin",
        password_encrypted=encrypt_secret("secret"),
        device_service_url="http://192.0.2.20:80/onvif/device_service",
        verification_status="unverified",
    )
    assert connection.adapter == "onvif"
    assert connection.verification_status == "unverified"
    assert connection.verified_at is None
    assert connection.onvif_config is not None
    assert connection.onvif_config.recording_profile_token is None
    assert connection.onvif_config.recording_uri is None
```

```python
def test_hik_connection_can_be_saved_unverified_without_discovered_metadata():
    camera = make_camera()
    connection = upsert_hik_connection(
        camera,
        host="192.0.2.30",
        username="admin",
        password_encrypted=encrypt_secret("secret"),
        sdk_port=8000,
        channel=1,
        main_stream_type=0,
        sub_stream_type=1,
        verification_status="unverified",
    )
    assert connection.adapter == "hik_sdk"
    assert connection.verification_status == "unverified"
    assert connection.hik_config is not None
    assert connection.hik_config.device_serial is None
```

- [ ] **Step 2: Run focused RED tests**

Run:

```bash
cd backend && pytest -q tests/test_unverified_adapter_connection.py tests/test_camera_connection_write.py
```

Expected: FAIL because ONVIF required cache fields and the current service signatures require a successful discovery timestamp/cache.

- [ ] **Step 3: Add the expand-only nullable ONVIF cache migration**

Create revision `20260917_0025`, down_revision `20260917_0024`, using SQLite-safe `batch_alter_table` to make only these columns nullable:

```text
onvif_connection_configs.recording_profile_token
onvif_connection_configs.recording_uri
```

Do not rewrite or backfill existing rows. Update ORM annotations for those two fields to `str | None` and `nullable=True`.

- [ ] **Step 4: Generalize strict ONVIF/HIK upserts without weakening adapter mismatch checks**

Keep strict same-adapter mismatch behavior. Normalize `capabilities=None` to `{}` and `profiles=None` to `[]`. When connection-defining fields change, increment revision once and replace verification state with the supplied state; an unverified ONVIF write must clear stale discovery-derived UUID/profile/token/URI cache. A no-op payload must preserve revision and existing verified/cache state.

- [ ] **Step 5: Verify migration + write GREEN**

Run:

```bash
cd backend && pytest -q tests/test_unverified_adapter_connection.py tests/test_camera_connection_write.py tests/test_camera_connection_migration.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add backend/migrations/versions/20260917_0025_onvif_unverified_connection.py backend/app/models/onvif_connection.py backend/app/services/camera_connection.py backend/tests/test_unverified_adapter_connection.py backend/tests/test_camera_connection_write.py backend/tests/test_camera_connection_migration.py
git commit -m "feat: allow unverified adapter connections"
```

---

### Task 2: Add canonical discriminated connection schemas and Camera read projection

**Files:**
- Create: `backend/app/schemas/camera_connection.py`
- Modify: `backend/app/schemas/camera.py`
- Create: `backend/tests/test_camera_connection_schema.py`
- Modify: `backend/tests/test_camera_connection_type.py`

**Interfaces:**
- Produces create drafts:
  - `ManualRtspConnectionCreate`
  - `OnvifConnectionCreate`
  - `HikConnectionCreate`
  - `CameraConnectionCreate = Annotated[union, Field(discriminator="adapter")]`
- Produces edit drafts with optional password:
  - `ManualRtspConnectionUpdate`
  - `OnvifConnectionUpdate`
  - `HikConnectionUpdate`
  - `CameraConnectionUpdate = Annotated[union, Field(discriminator="adapter")]`
- Produces `CameraConnectionRead` with `id`, `adapter`, `host`, `username`, `password_set`, `revision`, `verification_status`, `verified_at`, `last_error`, and adapter-specific `config`.
- Extends `CameraRead` with canonical `connection: CameraConnectionRead | None` while preserving current legacy response fields during the compatibility window.

- [ ] **Step 1: Write RED schema tests**

Cover discriminator validation for all three adapters, required create passwords, optional update passwords, adapter-specific field rejection, and ORM-to-read projection that never returns plaintext/encrypted passwords.

Example assertions:

```python
payload = CameraConnectionCreateAdapter.validate_python({
    "adapter": "manual_rtsp",
    "host": "192.0.2.10",
    "username": "admin",
    "password": "secret",
    "port": 554,
    "main_path": "/main",
})
assert payload.adapter == "manual_rtsp"
```

```python
read = CameraRead.model_validate(camera)
assert read.connection is not None
assert read.connection.adapter == camera.connection.adapter
assert read.connection.password_set is True
assert "password_encrypted" not in read.connection.model_dump()
```

- [ ] **Step 2: Run schema RED**

```bash
cd backend && pytest -q tests/test_camera_connection_schema.py tests/test_camera_connection_type.py
```

Expected: FAIL because canonical nested connection schemas/read projection do not exist.

- [ ] **Step 3: Implement focused schema module**

Use adapter literals and validation rules already present in legacy schemas:

```text
manual_rtsp: host, username, password, port=554, main_path, sub_path
onvif: host, username, password, port=80
hik_sdk: host, username, password, sdk_port=8000, channel=1, main_stream_type=0, sub_stream_type=1
```

Normalize host as hostname/IP only; reject schemes/paths. Keep `password` write-only by omitting it from all read models.

- [ ] **Step 4: Add canonical connection projection to `CameraRead`**

Use a Pydantic `model_validator(mode="before")` or equivalent focused helper to project SQLAlchemy `CameraConnection` plus its adapter config into `CameraConnectionRead`; retain legacy flat fields unchanged so the current frontend continues working until Phase 5.

- [ ] **Step 5: Run schema GREEN**

```bash
cd backend && pytest -q tests/test_camera_connection_schema.py tests/test_camera_connection_type.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add backend/app/schemas/camera_connection.py backend/app/schemas/camera.py backend/tests/test_camera_connection_schema.py backend/tests/test_camera_connection_type.py
git commit -m "feat: expose canonical camera connection contract"
```

---

### Task 3: Add adapter capability registry and unified draft probe endpoint

**Files:**
- Create: `backend/app/services/camera_adapter_registry.py`
- Create: `backend/app/services/camera_adapter_probe.py`
- Create: `backend/app/api/camera_connections.py`
- Modify: `backend/app/services/hik_bridge_client.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/onvif_cameras.py`
- Modify: `backend/app/api/hik_cameras.py`
- Create: `backend/tests/test_camera_adapter_registry.py`
- Create: `backend/tests/test_camera_connection_probe_api.py`
- Modify: `backend/tests/test_hik_bridge_client.py`

**Interfaces:**
- Produces `CameraAdapterCapability(id: str, label: str, available: bool, unavailable_reason: str | None)`.
- Produces `async def list_camera_adapter_capabilities() -> list[CameraAdapterCapability]`.
- Produces `async def probe_connection_draft(draft: CameraConnectionCreate | CameraConnectionUpdate, *, stored_password: str | None, rtsp_timeout_us: int) -> CameraConnectionProbeResult`.
- Produces public routes:
  - `GET /api/camera-adapters`
  - `POST /api/camera-connections/probe`
- Adds `HikBridgeClient.health() -> dict[str, object]` implemented as `GET /health`.

- [ ] **Step 1: Write RED registry tests**

Assert manual RTSP and ONVIF are reported available. Mock HIK bridge health success/failure and assert HIK remains visible in both cases, with `available=false` plus a reason on failure.

- [ ] **Step 2: Write RED unified probe tests**

Cover:

```text
manual draft -> media summary, no DB persistence
onvif draft -> device/discovery + media summary, no DB persistence
hik draft -> bridge discovery + media summary, no DB persistence
existing camera + omitted update password -> decrypt/reuse current stored password
new draft + omitted password -> 422
probe failure -> 502/adapter-specific error without mutating CameraConnection verification state
```

Snapshot the relevant Camera/CameraConnection before and after draft probe and assert equality.

- [ ] **Step 3: Run RED tests**

```bash
cd backend && pytest -q tests/test_camera_adapter_registry.py tests/test_camera_connection_probe_api.py tests/test_hik_bridge_client.py
```

Expected: FAIL because registry, endpoint, and HIK health client method are absent.

- [ ] **Step 4: Extract adapter probe/discovery logic into services**

Move ONVIF discovery/media validation and HIK bridge discovery/media validation out of route-private helpers into `camera_adapter_probe.py`. Dedicated `/api/cameras/onvif/probe` and `/api/cameras/hik/probe` become wrappers calling the same service primitives so there is one probe implementation.

`CameraConnectionProbeResult` must use one stable envelope:

```json
{
  "adapter": "onvif",
  "ok": true,
  "device": {},
  "media": {},
  "connection_cache": {}
}
```

Manual RTSP may return an empty `device`; ONVIF `connection_cache` contains credential-free discovery cache; HIK contains discovered serial/model/name/channel metadata. Never return credentials.

- [ ] **Step 5: Implement capability route and draft probe route**

For an update draft with `camera_id`, only reuse the stored password when the current connection exists and its adapter matches the draft adapter; otherwise require an explicit target password for a cross-adapter probe.

- [ ] **Step 6: Run Task 3 GREEN**

```bash
cd backend && pytest -q tests/test_camera_adapter_registry.py tests/test_camera_connection_probe_api.py tests/test_hik_bridge_client.py tests/test_onvif_cameras.py tests/test_hik_cameras.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/app/services/camera_adapter_registry.py backend/app/services/camera_adapter_probe.py backend/app/api/camera_connections.py backend/app/services/hik_bridge_client.py backend/app/main.py backend/app/api/onvif_cameras.py backend/app/api/hik_cameras.py backend/tests/test_camera_adapter_registry.py backend/tests/test_camera_connection_probe_api.py backend/tests/test_hik_bridge_client.py backend/tests/test_onvif_cameras.py backend/tests/test_hik_cameras.py
git commit -m "feat: add unified camera adapter probe api"
```

---

### Task 4: Add one camera mutation service for create, same-adapter edit, and adapter switch

**Files:**
- Create: `backend/app/services/camera_mutation.py`
- Modify: `backend/app/schemas/camera.py`
- Modify: `backend/app/api/cameras.py`
- Modify: `backend/app/api/camera_adapter_switch.py`
- Modify: `backend/app/api/onvif_cameras.py`
- Modify: `backend/app/api/hik_cameras.py`
- Create: `backend/tests/test_unified_camera_api.py`
- Modify: `backend/tests/test_camera_adapter_switch_api.py`
- Modify: `backend/tests/test_camera_adapter_switch_transaction.py`
- Modify: `backend/tests/test_adapter_edit_guard.py`

**Interfaces:**
- Produces `CameraUnifiedCreate` containing stable Camera metadata/policy plus required `connection: CameraConnectionCreate`.
- Produces `CameraUnifiedUpdate` containing optional metadata/policy plus optional `connection: CameraConnectionUpdate`.
- Produces `async def create_camera_from_unified_payload(db, payload) -> Camera`.
- Produces `async def update_camera_from_unified_payload(db, camera, payload) -> Camera`.
- `POST /api/cameras` accepts both the new nested unified create contract and the existing legacy flat manual RTSP create contract during the compatibility window.
- `PUT/PATCH /api/cameras/{id}` accepts the nested unified update contract; existing legacy flat manual RTSP update remains supported for the current frontend.

- [ ] **Step 1: Write RED unified create tests**

Create one disabled Camera for each adapter without monkeypatching network probes. Assert status 201, stable canonical `connection.adapter`, `verification_status="unverified"`, exactly one adapter config row, and password never appears in the response.

- [ ] **Step 2: Write RED same-adapter edit tests**

For each adapter assert:

```text
metadata-only edit -> no revision bump, no runtime teardown
identical connection payload -> no revision bump and preserves verified/cache state
real connection change -> revision +1, verification becomes unverified
omitted password -> keeps existing encrypted password
```

- [ ] **Step 3: Write RED cross-adapter switch tests**

Exercise all target adapters through `PUT/PATCH /api/cameras/{id}` using nested `connection`. Assert Camera ID and CameraConnection ID stay stable, revision increments once, stale adapter config is removed, invalid schedule fails before coordinator teardown, and the new adapter can be saved unverified without a network probe.

- [ ] **Step 4: Preserve the proven switch transaction failure tests**

Adapt existing transaction tests to call the unified endpoint and keep these exact invariants:

```text
persistence failure -> rollback -> restore old runtime/config
post-commit restore failure -> new connection remains persisted and failure surfaces
stop_all happens once for a real cross-adapter switch
```

Do not replace these with commit-before-stop semantics.

- [ ] **Step 5: Run Task 4 RED**

```bash
cd backend && pytest -q tests/test_unified_camera_api.py tests/test_camera_adapter_switch_api.py tests/test_camera_adapter_switch_transaction.py tests/test_adapter_edit_guard.py
```

Expected: FAIL because the generic endpoint cannot yet create/update ONVIF/HIK through nested connection drafts.

- [ ] **Step 6: Implement `camera_mutation.py` as the only frontend-facing mutation orchestration**

Responsibilities:

```text
validate schedule/payload before runtime teardown
resolve create/update password rules
apply Camera metadata/policy
choose strict same-adapter upsert vs explicit switch_to_* function
write unverified connection state when no persisted probe result is being applied
preserve rollback shadow fields through existing camera_connection writers
emit non-secret audit/event summaries
coordinate stop/commit/restore only when the connection adapter changes
reload current runtime for same-adapter connection changes or policy changes using existing coordinator semantics
```

Do not duplicate adapter config field writes in API modules.

- [ ] **Step 7: Make dedicated adapter routes compatibility wrappers**

Convert ONVIF/HIK create/update routes to translate their legacy request schema into the unified mutation service. Preserve their existing URLs and response shape for the current frontend/tests, but remove independent persistence/orchestration logic.

`camera_adapter_switch.py` should no longer own a separate manual-switch implementation once the generic camera endpoint can switch to manual RTSP.

- [ ] **Step 8: Run Task 4 GREEN**

```bash
cd backend && pytest -q tests/test_unified_camera_api.py tests/test_camera_adapter_switch_api.py tests/test_camera_adapter_switch_transaction.py tests/test_adapter_edit_guard.py tests/test_camera_connection_switch.py tests/test_camera_connection_write.py
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```bash
git add backend/app/services/camera_mutation.py backend/app/schemas/camera.py backend/app/api/cameras.py backend/app/api/camera_adapter_switch.py backend/app/api/onvif_cameras.py backend/app/api/hik_cameras.py backend/tests/test_unified_camera_api.py backend/tests/test_camera_adapter_switch_api.py backend/tests/test_camera_adapter_switch_transaction.py backend/tests/test_adapter_edit_guard.py backend/tests/test_camera_connection_switch.py backend/tests/test_camera_connection_write.py
git commit -m "feat: unify camera create and adapter updates"
```

---

### Task 5: Make persisted current-connection probe adapter-aware and update verification/cache safely

**Files:**
- Modify: `backend/app/services/camera_adapter_probe.py`
- Modify: `backend/app/api/cameras.py`
- Create: `backend/tests/test_camera_current_connection_probe.py`
- Modify: `backend/tests/test_camera_probe_state.py`
- Modify: `backend/tests/test_camera_runtime_coordinator.py`

**Interfaces:**
- Existing `POST /api/cameras/{camera_id}/probe` becomes adapter-aware for the saved current connection.
- Successful probe updates `verification_status="verified"`, `verified_at`, clears `last_error`, refreshes device/media cache and Camera media fields, then reloads runtime only when newly materialized adapter cache is required by runtime.
- Failed probe updates `verification_status="failed"`, `last_error`, Camera connectivity observation, but does not alter target endpoint/credentials/revision.

- [ ] **Step 1: Write RED persisted probe tests**

Start from unverified manual, ONVIF, and HIK connections. Mock adapter probe success and assert verification state and cache become verified/materialized without a connection revision bump. Mock failure and assert revision/endpoint/credentials stay unchanged while status becomes failed.

- [ ] **Step 2: Run RED**

```bash
cd backend && pytest -q tests/test_camera_current_connection_probe.py tests/test_camera_probe_state.py
```

Expected: FAIL for ONVIF/HIK because the current endpoint still assumes an already-materialized runtime stream.

- [ ] **Step 3: Implement adapter-aware persisted probe**

Reuse `camera_adapter_probe.py`; do not call dedicated route handlers. For ONVIF, persist credential-free discovery cache into the existing `OnvifConnectionConfig`; for HIK, persist serial/model/name discovery metadata; for all adapters update Camera media capability fields from the standardized probe result.

Probe-derived cache refresh is verification data, not a user connection edit: it must not increment connection revision unless the user-visible connection target itself changed.

- [ ] **Step 4: Run GREEN**

```bash
cd backend && pytest -q tests/test_camera_current_connection_probe.py tests/test_camera_probe_state.py tests/test_camera_runtime_coordinator.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add backend/app/services/camera_adapter_probe.py backend/app/api/cameras.py backend/tests/test_camera_current_connection_probe.py backend/tests/test_camera_probe_state.py backend/tests/test_camera_runtime_coordinator.py
git commit -m "feat: probe saved camera connections by adapter"
```

---

### Task 6: Regression, compatibility, and migration-status closure

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`
- Modify only if tests prove necessary: `backend/app/main.py`
- Test: all backend camera/adapter tests plus Docker migration smoke.

**Interfaces:**
- Dedicated ONVIF/HIK endpoints remain working wrappers.
- Legacy manual flat create/update remains working until Phase 5 migrates the frontend.
- Canonical nested `connection` is present in Camera reads and is the source Phase 5 will consume.
- Phase 3 checklist items in the architecture migration/status docs are marked complete only after final CI is green.

- [ ] **Step 1: Run focused adapter/camera regression suite**

```bash
cd backend && pytest -q \
  tests/test_unified_camera_api.py \
  tests/test_camera_adapter_registry.py \
  tests/test_camera_connection_probe_api.py \
  tests/test_camera_current_connection_probe.py \
  tests/test_camera_adapter_switch_api.py \
  tests/test_camera_adapter_switch_transaction.py \
  tests/test_camera_connection_write.py \
  tests/test_camera_connection_switch.py \
  tests/test_camera_runtime_coordinator.py \
  tests/test_onvif_cameras.py \
  tests/test_hik_cameras.py
```

Expected: PASS.

- [ ] **Step 2: Run backend quality and full backend tests**

```bash
cd backend && python -m compileall app tests
cd backend && ruff check app tests
cd backend && pytest -q
```

Expected: PASS.

- [ ] **Step 3: Verify Alembic upgrade compatibility**

Run the repository's existing migration compatibility test/smoke path and confirm revision `0025` upgrades an existing `0024` database without changing Camera IDs, CameraConnection IDs, or existing ONVIF cache values.

- [ ] **Step 4: Update migration status documentation**

Mark these Phase 3 items complete:

```text
adapter capability registry + API
unified adapter-aware draft probe
unified create API connection object
unified update/same-adapter/switch API
frontend-facing deprecation of adapter-specific persistence semantics (routes retained as wrappers)
structured deletion-impact remains already complete
```

Do not mark Phase 4 HIK optional deployment or Phase 5 UI items complete.

- [ ] **Step 5: Commit Task 6**

```bash
git add docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md
git commit -m "docs: mark unified camera adapter api complete"
```

- [ ] **Step 6: Open/update PR and require final head CI**

PR title:

```text
feat: unify camera adapter api
```

Final evidence must be from the PR's latest head and include all backend pytest shards, backend quality/Ruff, HIK bridge tests, Docker build/start smoke, database migration compatibility, and aggregate backend success. Frontend may be skipped when no frontend source changes are included.
