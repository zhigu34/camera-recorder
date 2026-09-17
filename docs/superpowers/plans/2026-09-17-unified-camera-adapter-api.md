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
- Create: `backend/tests/test_unverified_adapter_connection.py`
- Modify: `backend/tests/test_camera_connection_write.py`
- Modify: `backend/tests/test_onvif_connection_migration.py`
- Modify: `backend/tests/test_hik_connection_write.py`

**Interfaces:**
- Produce `upsert_onvif_connection(camera, *, host: str, username: str, password_encrypted: str, device_service_url: str, device_uuid: str | None = None, capabilities: dict | None = None, profiles: list[dict] | None = None, recording_profile_token: str | None = None, preview_profile_token: str | None = None, detection_profile_token: str | None = None, recording_uri: str | None = None, preview_uri: str | None = None, detection_uri: str | None = None, verification_status: str = "unverified", verified_at: datetime | None = None, last_error: str | None = None) -> CameraConnection`.
- Produce `upsert_hik_connection(camera, *, host: str, username: str, password_encrypted: str, sdk_port: int, channel: int, main_stream_type: int, sub_stream_type: int, device_serial: str | None = None, device_model: str | None = None, device_name: str | None = None, verification_status: str = "unverified", verified_at: datetime | None = None, last_error: str | None = None) -> CameraConnection`.
- Preserve strict adapter mismatch checks and existing switch identity semantics.

- [ ] **Step 1: Write RED tests for unverified ONVIF/HIK persistence**

Add `test_unverified_adapter_connection.py` with direct service tests that call the new keyword arguments against today's implementation. The RED must occur in test bodies, not during collection.

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
    assert connection.verified_at is None
    assert connection.hik_config is not None
    assert connection.hik_config.device_serial is None
```

Also add a no-op regression for each adapter: re-submit identical canonical fields with default unverified arguments to an already verified connection and assert revision, verification status, and verified discovery cache stay unchanged.

- [ ] **Step 2: Run focused RED tests**

```bash
cd backend && pytest -q tests/test_unverified_adapter_connection.py tests/test_camera_connection_write.py tests/test_hik_connection_write.py
```

Expected: FAIL in test bodies because the ONVIF/HIK service signatures require successful-discovery arguments and always write `verified`.

- [ ] **Step 3: Write RED migration test for nullable ONVIF discovery cache**

Extend `test_onvif_connection_migration.py` to upgrade a database from revision `20260917_0024` to head and assert `PRAGMA table_info(onvif_connection_configs)` reports `notnull=0` for `recording_profile_token` and `recording_uri`, while an existing populated ONVIF row retains its values.

- [ ] **Step 4: Add expand-only migration and ORM nullability**

Create revision `20260917_0025`, down_revision `20260917_0024`. Use SQLite-safe `batch_alter_table` to alter exactly:

```text
onvif_connection_configs.recording_profile_token -> nullable=True
onvif_connection_configs.recording_uri -> nullable=True
```

Do not backfill, clear, or rewrite existing ONVIF rows. Update the ORM annotations for those two fields to `Mapped[str | None]` with `nullable=True`.

- [ ] **Step 5: Generalize strict ONVIF/HIK upserts**

Normalize `capabilities=None` to `{}` and `profiles=None` to `[]`. When connection-defining fields truly change, increment revision once and apply the requested verification state. An unverified ONVIF connection change clears discovery-derived UUID/profile/token/URI cache. A no-op write preserves the existing verified state/cache and does not increment revision. Keep rollback shadow writes intact.

- [ ] **Step 6: Run Task 1 GREEN**

```bash
cd backend && pytest -q tests/test_unverified_adapter_connection.py tests/test_camera_connection_write.py tests/test_hik_connection_write.py tests/test_onvif_connection_migration.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add backend/migrations/versions/20260917_0025_onvif_unverified_connection.py backend/app/models/onvif_connection.py backend/app/services/camera_connection.py backend/tests/test_unverified_adapter_connection.py backend/tests/test_camera_connection_write.py backend/tests/test_hik_connection_write.py backend/tests/test_onvif_connection_migration.py
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
- Produce `ManualRtspConnectionCreate`, `OnvifConnectionCreate`, `HikConnectionCreate` and `CameraConnectionCreate = Annotated[ManualRtspConnectionCreate | OnvifConnectionCreate | HikConnectionCreate, Field(discriminator="adapter")]`.
- Produce `ManualRtspConnectionUpdate`, `OnvifConnectionUpdate`, `HikConnectionUpdate` and `CameraConnectionUpdate = Annotated[ManualRtspConnectionUpdate | OnvifConnectionUpdate | HikConnectionUpdate, Field(discriminator="adapter")]`.
- Produce adapter-specific read config models and `CameraConnectionRead` with `id`, `adapter`, `host`, `username`, `password_set`, `revision`, `verification_status`, `verified_at`, `last_error`, and `config`.
- Extend `CameraRead` with `connection: CameraConnectionRead | None` while preserving current legacy response fields during the compatibility window.

- [ ] **Step 1: Write RED schema tests**

Cover all three discriminators, required create passwords, optional update passwords, adapter-specific field rejection, and ORM-to-read projection that never returns plaintext/encrypted passwords.

```python
from pydantic import TypeAdapter

adapter = TypeAdapter(CameraConnectionCreate)
payload = adapter.validate_python({
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

Expected: FAIL because nested connection schemas/read projection do not exist.

- [ ] **Step 3: Implement focused schema module**

Use exact adapter fields:

```text
manual_rtsp: host, username, password, port=554, main_path, sub_path
onvif: host, username, password, port=80
hik_sdk: host, username, password, sdk_port=8000, channel=1, main_stream_type=0, sub_stream_type=1
```

Create variants require `password`; update variants allow `password=None`. Normalize host as hostname/IP only and reject schemes/paths. Read models never expose `password` or `password_encrypted`.

- [ ] **Step 4: Add canonical connection projection to `CameraRead`**

Add a focused projection helper that reads `CameraConnection` and its active adapter config. Keep legacy flat fields unchanged so the current frontend remains functional until Phase 5.

- [ ] **Step 5: Run Task 2 GREEN**

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
- Modify: `backend/tests/test_onvif_camera_api.py`
- Modify: `backend/tests/test_hik_camera_api.py`

**Interfaces:**
- Produce `CameraAdapterCapability(id: str, label: str, available: bool, unavailable_reason: str | None)`.
- Produce `async def list_camera_adapter_capabilities() -> list[CameraAdapterCapability]`.
- Produce `CameraConnectionProbeResult(adapter: CameraConnectionType, ok: bool, device: dict[str, object], media: dict[str, object], connection_cache: dict[str, object])`.
- Produce `async def probe_connection_draft(draft: CameraConnectionCreate | CameraConnectionUpdate, *, password: str, rtsp_timeout_us: int) -> CameraConnectionProbeResult`.
- Add `HikBridgeClient.health() -> dict[str, object]` implemented as `GET /health`.
- Add public `GET /api/camera-adapters` and `POST /api/camera-connections/probe`.

- [ ] **Step 1: Write RED registry tests**

Assert manual RTSP and ONVIF report `available=true`. Mock HIK bridge `/health` success and transport/error responses; HIK must remain present and switch to `available=false` with a non-empty reason when unhealthy.

- [ ] **Step 2: Write RED unified draft-probe tests**

Cover these exact cases:

```text
manual create draft with password -> standardized media result, no DB mutation
onvif create draft with password -> standardized device/media/cache result, no DB mutation
hik create draft with password -> standardized device/media/cache result, no DB mutation
same-adapter existing camera + update draft without password -> route decrypts/reuses current stored password
cross-adapter existing camera + target draft without password -> 422
create draft without password -> 422 at schema validation
probe failure -> 502/adapter-specific error, no CameraConnection verification/revision mutation
```

Snapshot CameraConnection fields before/after draft probe and assert exact equality.

- [ ] **Step 3: Run RED**

```bash
cd backend && pytest -q tests/test_camera_adapter_registry.py tests/test_camera_connection_probe_api.py tests/test_hik_bridge_client.py
```

Expected: FAIL because the registry, unified endpoint, and HIK health method are absent.

- [ ] **Step 4: Extract adapter probe/discovery logic into `camera_adapter_probe.py`**

Move ONVIF discovery/media validation and HIK bridge discovery/media validation out of route-private helpers. The legacy `/api/cameras/onvif/probe` and `/api/cameras/hik/probe` route handlers call these service functions rather than owning separate probe implementations.

Return one envelope:

```json
{
  "adapter": "onvif",
  "ok": true,
  "device": {},
  "media": {},
  "connection_cache": {}
}
```

Manual RTSP uses an empty `device`; ONVIF `connection_cache` contains credential-free discovery values; HIK `device`/cache contains bridge-discovered non-secret metadata. No response field may contain username/password credentials embedded into stream URIs.

- [ ] **Step 5: Implement capability and draft-probe routes**

The request contains `camera_id: int | None` plus a discriminated `connection` draft. If an update draft omits password, reuse the stored password only when the referenced Camera exists and the current adapter matches the draft adapter. Cross-adapter draft probe requires explicit target password.

- [ ] **Step 6: Run Task 3 GREEN**

```bash
cd backend && pytest -q tests/test_camera_adapter_registry.py tests/test_camera_connection_probe_api.py tests/test_hik_bridge_client.py tests/test_onvif_camera_api.py tests/test_hik_camera_api.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/app/services/camera_adapter_registry.py backend/app/services/camera_adapter_probe.py backend/app/api/camera_connections.py backend/app/services/hik_bridge_client.py backend/app/main.py backend/app/api/onvif_cameras.py backend/app/api/hik_cameras.py backend/tests/test_camera_adapter_registry.py backend/tests/test_camera_connection_probe_api.py backend/tests/test_hik_bridge_client.py backend/tests/test_onvif_camera_api.py backend/tests/test_hik_camera_api.py
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
- Produce `CameraUnifiedCreate` containing Camera identity/policy fields plus required `connection: CameraConnectionCreate`.
- Produce `CameraUnifiedUpdate` containing optional identity/policy fields plus optional `connection: CameraConnectionUpdate`.
- Keep current legacy `CameraCreate`/`CameraUpdate` as flat manual RTSP compatibility models.
- Define `CameraCreateRequest = CameraUnifiedCreate | CameraCreate` and `CameraUpdateRequest = CameraUnifiedUpdate | CameraUpdate` for route compatibility.
- Produce `async def create_camera_from_unified_payload(db: AsyncSession, payload: CameraUnifiedCreate) -> Camera`.
- Produce `async def update_camera_from_unified_payload(db: AsyncSession, camera: Camera, payload: CameraUnifiedUpdate) -> Camera`.

- [ ] **Step 1: Write RED unified-create tests**

Create one disabled Camera for each adapter through `POST /api/cameras` with nested `connection` and no monkeypatched network probe. Assert 201, correct canonical adapter, `verification_status="unverified"`, exactly one target config row, and no credential data in response.

- [ ] **Step 2: Write RED same-adapter edit tests**

For each adapter prove:

```text
metadata-only edit -> no revision bump and no runtime teardown
identical connection draft -> no revision bump and preserves verified/cache state
real connection change -> revision +1 and verification becomes unverified
omitted update password -> keeps existing encrypted password
```

- [ ] **Step 3: Write RED cross-adapter switch tests**

Exercise switches to each target adapter through `PUT /api/cameras/{id}` using nested `connection`. Assert Camera ID and CameraConnection ID stay stable, revision increments once, stale adapter config is removed, invalid schedule fails before coordinator teardown, and the target connection can be persisted unverified without network access.

- [ ] **Step 4: Port existing transaction-failure assertions to the unified endpoint**

Keep these invariants exactly:

```text
persistence failure -> rollback -> restore old runtime/config
post-commit restore failure -> new connection remains persisted and failure surfaces
stop_all occurs once for a real cross-adapter switch
```

Do not implement commit-before-stop semantics.

- [ ] **Step 5: Run Task 4 RED**

```bash
cd backend && pytest -q tests/test_unified_camera_api.py tests/test_camera_adapter_switch_api.py tests/test_camera_adapter_switch_transaction.py tests/test_adapter_edit_guard.py
```

Expected: FAIL because the generic endpoint cannot create/update ONVIF/HIK through nested connection drafts.

- [ ] **Step 6: Implement `camera_mutation.py`**

The service owns these exact responsibilities: prevalidate recording schedule/payload before teardown; resolve create/update password rules; apply Camera metadata/policy; choose strict same-adapter upsert vs explicit `switch_to_manual_rtsp_connection` / `switch_to_onvif_connection` / `switch_to_hik_connection`; write `unverified` when no persisted probe result is being applied; preserve rollback shadow fields through existing writers; emit non-secret audit/event summaries; coordinate `stop_all -> commit -> restore` for adapter changes; use existing coordinator reload behavior for same-adapter connection/policy changes.

Adapter field writes remain inside `camera_connection.py`; route modules must not duplicate them.

- [ ] **Step 7: Convert dedicated routes to compatibility wrappers**

Translate legacy ONVIF/HIK create/update payloads into the unified mutation service. Preserve their URLs and successful response shape. Remove independent adapter persistence/orchestration from those routes. Once the generic endpoint handles switches to manual RTSP, `camera_adapter_switch.py` becomes a thin compatibility delegation or is removed from router registration if all legacy generic requests are handled directly by `cameras.py`.

- [ ] **Step 8: Run Task 4 GREEN**

```bash
cd backend && pytest -q tests/test_unified_camera_api.py tests/test_camera_adapter_switch_api.py tests/test_camera_adapter_switch_transaction.py tests/test_adapter_edit_guard.py tests/test_camera_connection_switch.py tests/test_camera_connection_write.py tests/test_onvif_camera_api.py tests/test_hik_camera_api.py tests/test_hik_canonical_api.py
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```bash
git add backend/app/services/camera_mutation.py backend/app/schemas/camera.py backend/app/api/cameras.py backend/app/api/camera_adapter_switch.py backend/app/api/onvif_cameras.py backend/app/api/hik_cameras.py backend/tests/test_unified_camera_api.py backend/tests/test_camera_adapter_switch_api.py backend/tests/test_camera_adapter_switch_transaction.py backend/tests/test_adapter_edit_guard.py backend/tests/test_camera_connection_switch.py backend/tests/test_camera_connection_write.py backend/tests/test_onvif_camera_api.py backend/tests/test_hik_camera_api.py backend/tests/test_hik_canonical_api.py
git commit -m "feat: unify camera create and adapter updates"
```

---

### Task 5: Make persisted current-connection probe adapter-aware

**Files:**
- Modify: `backend/app/services/camera_adapter_probe.py`
- Modify: `backend/app/api/cameras.py`
- Create: `backend/tests/test_camera_current_connection_probe.py`
- Modify: `backend/tests/test_camera_probe.py`
- Modify: `backend/tests/test_camera_probe_adapter.py`

**Interfaces:**
- `POST /api/cameras/{camera_id}/probe` probes the saved canonical current connection regardless of adapter.
- Success sets `verification_status="verified"`, sets `verified_at`, clears `last_error`, refreshes non-secret adapter discovery cache and Camera media fields, and never bumps connection revision solely for probe-derived cache refresh.
- Failure sets `verification_status="failed"` and `last_error`, updates connectivity observation, and leaves endpoint/credentials/revision unchanged.

- [ ] **Step 1: Write RED persisted-probe tests**

Start from unverified manual RTSP, ONVIF, and HIK connections. Mock standardized service probe success and assert verification/cache/media fields become materialized without revision change. Mock failure and assert revision, adapter target fields, and credentials remain unchanged while verification becomes failed.

- [ ] **Step 2: Run RED**

```bash
cd backend && pytest -q tests/test_camera_current_connection_probe.py tests/test_camera_probe.py tests/test_camera_probe_adapter.py
```

Expected: FAIL for ONVIF/HIK because the current endpoint still assumes an already-materialized runtime stream.

- [ ] **Step 3: Implement adapter-aware persisted probe**

Reuse `camera_adapter_probe.py`, never dedicated route handlers. ONVIF success persists credential-free device/profile/token/URI cache into `OnvifConnectionConfig`; HIK success persists serial/model/name discovery metadata; all adapters refresh Camera media capability fields. Probe-derived cache refresh does not increment revision because it is verification metadata, not a user target edit.

- [ ] **Step 4: Run Task 5 GREEN**

```bash
cd backend && pytest -q tests/test_camera_current_connection_probe.py tests/test_camera_probe.py tests/test_camera_probe_adapter.py tests/test_camera_runtime_coordinator.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add backend/app/services/camera_adapter_probe.py backend/app/api/cameras.py backend/tests/test_camera_current_connection_probe.py backend/tests/test_camera_probe.py backend/tests/test_camera_probe_adapter.py
git commit -m "feat: probe saved camera connections by adapter"
```

---

### Task 6: Regression, compatibility, and migration-status closure

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`

**Interfaces:**
- Dedicated ONVIF/HIK endpoints remain working wrappers.
- Legacy manual flat create/update remains working until Phase 5 migrates the frontend.
- Canonical nested `connection` is present in Camera reads and is the source Phase 5 consumes.
- Mark Phase 3 complete only after final-head CI is green.

- [ ] **Step 1: Run focused adapter/camera regression suite**

```bash
cd backend && pytest -q tests/test_unified_camera_api.py tests/test_camera_adapter_registry.py tests/test_camera_connection_probe_api.py tests/test_camera_current_connection_probe.py tests/test_camera_adapter_switch_api.py tests/test_camera_adapter_switch_transaction.py tests/test_camera_connection_write.py tests/test_hik_connection_write.py tests/test_camera_connection_switch.py tests/test_camera_runtime_coordinator.py tests/test_onvif_camera_api.py tests/test_hik_camera_api.py tests/test_hik_canonical_api.py
```

Expected: PASS.

- [ ] **Step 2: Run exact migration compatibility tests**

```bash
cd backend && pytest -q tests/test_camera_connection_migration.py tests/test_onvif_connection_migration.py tests/test_hik_connection_migration.py tests/test_camera_connection_phase1_upgrade.py
```

Expected: PASS, including `0024 -> 0025` upgrade with unchanged Camera/CameraConnection identities and preserved populated ONVIF cache values.

- [ ] **Step 3: Run backend quality and complete backend suite**

```bash
cd backend && python -m compileall app tests
cd backend && ruff check app tests
cd backend && pytest -q
```

Expected: PASS.

- [ ] **Step 4: Update migration status documentation**

Record Phase 3 completion for adapter capability registry/API, unified draft probe, nested connection create/update, same-adapter edit and explicit adapter switching through the generic Camera API, and dedicated adapter routes as compatibility wrappers. Keep Phase 4 HIK optional deployment, Phase 5 split-view UI, and Contract cleanup explicitly open.

- [ ] **Step 5: Commit Task 6**

```bash
git add docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md
git commit -m "docs: mark unified camera adapter api complete"
```

- [ ] **Step 6: Open/update PR and require final-head CI**

Use PR title `feat: unify camera adapter api`. Final evidence must be from the PR's latest head and include all backend pytest shards, backend quality/Ruff, HIK bridge tests, Docker build/start smoke, database migration compatibility, and aggregate backend success. Frontend may be skipped when no frontend source changes are included.
