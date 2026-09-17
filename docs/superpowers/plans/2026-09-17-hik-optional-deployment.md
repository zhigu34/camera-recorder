# HIK Optional Deployment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Hikvision HCNetSDK support default-off and truly optional so the core deployment runs without the proprietary SDK or bridge, while preserving existing HIK camera configuration and preventing unavailable HIK runtime from being misreported as device offline.

**Architecture:** Keep one Compose file with `hik-bridge` behind the `hik` profile and keep core services independent. Add one backend deployment capability flag (`CAMREC_HIK_ENABLED`) and one canonical capability resolver used by adapter reporting, runtime restoration, connectivity monitoring, probe paths, and HIK media startup. Preserve Phase 3 persistence semantics: HIK connection configuration can still be saved while capability is unavailable; only runtime/device-access operations are gated. Refactor `deploy.sh` into core-first deployment plus an optional HIK stage so HIK failure cannot roll back healthy core services.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLAlchemy, pytest/pytest-asyncio, Docker Compose profiles, Bash, GitHub Actions.

---

## Task 1: Add deployment flag and canonical HIK capability resolution

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/camera_adapter_registry.py`
- Modify: `backend/tests/test_camera_adapter_registry.py`

### Step 1: Write RED tests

Extend `test_camera_adapter_registry.py` to require:

- `Settings(_env_file=None).hik_enabled is False`.
- When `settings.hik_enabled=False`, HIK remains visible but unavailable with reason `HIK SDK adapter is disabled by deployment configuration`.
- Disabled capability resolution must not construct/call `HikBridgeClient`.
- When enabled, bridge health must be checked.
- `runtime_available=True` is required for HIK to be available.
- HTTP success with `runtime_available=False` keeps HIK unavailable.
- A bridge exception keeps HIK unavailable with a sanitized reason.
- Manual RTSP and ONVIF remain available regardless of HIK state.

Use module-level monkeypatches for `registry.settings.hik_enabled` and `registry.HikBridgeClient`; do not mutate process environment between tests.

### Step 2: Run RED

Run:

```bash
cd backend
uv run python -m pytest tests/test_camera_adapter_registry.py -q
```

Expected: failures because `Settings.hik_enabled` does not exist, disabled mode still calls bridge health, and the current registry ignores `runtime_available`.

### Step 3: Implement minimal GREEN

In `config.py` add:

```python
hik_enabled: bool = False
```

In `camera_adapter_registry.py`:

- define one canonical disabled reason constant;
- add a helper that resolves a single adapter capability without calling HIK for built-ins;
- for HIK, short-circuit on `settings.hik_enabled is False`;
- when enabled, call `HikBridgeClient().health()`;
- require `runtime_available is True` before returning available;
- return sanitized unavailable reasons for bridge/runtime failures;
- make `list_camera_adapter_capabilities()` compose the three capabilities through that helper.

Do not add database state and do not persist capability results.

### Step 4: Run GREEN + quality

```bash
cd backend
uv run python -m pytest tests/test_camera_adapter_registry.py tests/test_hik_bridge_client.py -q
uv run ruff check app tests migrations ci_test_shards.py
```

Expected: all pass.

### Step 5: Commit

```bash
git add backend/app/core/config.py backend/app/services/camera_adapter_registry.py backend/tests/test_camera_adapter_registry.py
git commit -m "feat: gate hik adapter capability by deployment"
```

---

## Task 2: Gate HIK runtime, connectivity, probe, and media access

**Files:**
- Modify: `backend/app/services/camera_adapter_registry.py`
- Modify: `backend/app/services/camera_adapter_probe.py`
- Modify: `backend/app/services/camera_runtime_coordinator.py`
- Modify: `backend/app/services/camera_connectivity_monitor.py`
- Modify: `backend/app/api/camera_adapter_switch.py`
- Modify: `backend/app/api/hik_media.py`
- Modify: `backend/app/api/hik_cameras.py`
- Modify: `backend/tests/test_camera_runtime_coordinator.py`
- Modify: `backend/tests/test_camera_connectivity_monitor.py`
- Modify: `backend/tests/test_hik_connectivity.py`
- Modify: `backend/tests/test_camera_connection_probe_api.py`
- Modify: `backend/tests/test_camera_current_connection_probe.py`
- Modify: `backend/tests/test_hik_media_session_lifecycle.py`
- Modify: `backend/tests/test_hik_camera_api.py`
- Modify: `backend/tests/test_unified_camera_api.py`

### Step 1: Write RED runtime/coordinator tests

Add a coordinator test using an enabled `hik_sdk` camera whose capability resolver returns unavailable. Require:

- `reload()` still performs the existing stop phase first;
- restore returns `adapter_unavailable`;
- schedule is detached/forgotten into a non-running state as appropriate;
- recorder restart, schedule reconcile, event pre-roll reconcile, and motion restart are not called;
- the result type accepts `adapter_unavailable`.

Also keep existing manual/ONVIF restore tests green.

### Step 2: Write RED connectivity tests

Add a monitor test for an enabled HIK camera with previously persisted connectivity state/failure count and unavailable capability. Require:

- no password decryption/bridge probe call;
- no increment of connectivity failures;
- no rewrite to `offline`;
- no new `last_probe_at` solely because capability is unavailable.

Resolve HIK capability once per monitor cycle rather than once per camera.

### Step 3: Write RED HIK operation tests

Add/extend tests so HIK unavailable/disabled returns a dedicated capability-unavailable error before bridge access:

- unified draft `POST /api/camera-connections/probe` -> HTTP 503 and no bridge call;
- persisted `POST /api/cameras/{id}/probe` -> HTTP 503 **without** changing connection verification, revision, target, camera status, failure count, or probe timestamps;
- internal `hik_media()` -> HTTP 503 and no stream creation;
- legacy `/api/cameras/hik/probe` -> HTTP 503 and no bridge call.

Add one unified API test proving a HIK connection can still be created/saved `unverified` while HIK is disabled; persistence must not call capability/bridge.

### Step 4: Run RED

```bash
cd backend
uv run python -m pytest \
  tests/test_camera_runtime_coordinator.py \
  tests/test_camera_connectivity_monitor.py \
  tests/test_hik_connectivity.py \
  tests/test_camera_connection_probe_api.py \
  tests/test_camera_current_connection_probe.py \
  tests/test_hik_media_session_lifecycle.py \
  tests/test_hik_camera_api.py \
  tests/test_unified_camera_api.py -q
```

Expected: failures because runtime restoration, monitor, probe, and media paths currently do not share a capability guard, and persisted probe treats 503 like a device failure.

### Step 5: Implement minimal GREEN

In `camera_adapter_registry.py` add a reusable capability requirement helper and a dedicated exception, for example:

```python
class CameraAdapterUnavailableError(RuntimeError):
    def __init__(self, adapter: str, reason: str): ...
```

`require_camera_adapter_available(adapter)` should:

- return immediately for available adapters;
- raise the dedicated exception when unavailable;
- never persist anything.

Use that boundary as follows:

- `camera_runtime_coordinator.restore()` checks the current canonical adapter after missing/disabled guards and before any worker restore; on unavailable, leave workers stopped and return `adapter_unavailable`.
- `camera_connectivity_monitor.check_once()` resolves HIK availability once. Exclude unavailable HIK targets from active probe/persistence work while preserving their persisted connectivity state.
- `camera_adapter_probe._probe_hik()` calls the requirement helper before constructing `HikBridgeClient`; translate unavailable to `CameraAdapterProbeError(..., status_code=503)` via a dedicated subtype or flag.
- `camera_adapter_switch.probe_current_connection()` catches capability-unavailable separately so it does **not** call `apply_probe_failure`, set `camera.status="offline"`, increment failures, or update probe timestamps.
- `hik_media.hik_media()` requires HIK capability before building/creating bridge streams and returns 503 on unavailable.
- legacy `hik_cameras._probe_hik()` uses the same guard before bridge access; compatibility create/update may therefore still require available HIK, while unified create/update remains the offline-save path.

Do not change connection revision or credentials due capability state.

### Step 6: Run GREEN + regressions

```bash
cd backend
uv run python -m pytest \
  tests/test_camera_adapter_registry.py \
  tests/test_camera_runtime_coordinator.py \
  tests/test_camera_connectivity_monitor.py \
  tests/test_hik_connectivity.py \
  tests/test_camera_connection_probe_api.py \
  tests/test_camera_current_connection_probe.py \
  tests/test_hik_media_session_lifecycle.py \
  tests/test_hik_camera_api.py \
  tests/test_hik_canonical_api.py \
  tests/test_unified_camera_api.py \
  tests/test_unverified_adapter_connection.py -q
uv run ruff check app tests migrations ci_test_shards.py
```

Expected: all pass.

### Step 7: Commit

```bash
git add backend/app backend/tests
git commit -m "feat: stop hik runtime access when unavailable"
```

---

## Task 3: Make Compose HIK profile default-off

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `backend/tests/test_hik_deploy_contract.py`

### Step 1: Rewrite/extend RED deployment-contract tests

Update the existing deployment contract instead of creating a parallel file. Require:

- `services.hik-bridge.profiles == ["hik"]`;
- backend does not depend on `hik-bridge` at all;
- backend environment contains `CAMREC_HIK_ENABLED: ${CAMREC_HIK_ENABLED:-0}`;
- `.env.example` contains `CAMREC_HIK_ENABLED=0` adjacent to HIK settings;
- existing bridge runtime mount and `HIK_SDK_PATH` remain intact;
- `LD_LIBRARY_PATH` remains absent from Compose environment.

Replace the old test that asserts backend `depends_on.hik-bridge.condition == service_started` with the new independence assertion.

### Step 2: Run RED

```bash
cd backend
uv run python -m pytest tests/test_hik_deploy_contract.py -q
```

Expected: failures because bridge has no profile, backend still depends on it, and the env flag is absent.

### Step 3: Implement minimal GREEN

Modify Compose:

```yaml
hik-bridge:
  profiles: ["hik"]
```

Delete only the backend -> HIK `depends_on` block. Add backend env:

```yaml
CAMREC_HIK_ENABLED: ${CAMREC_HIK_ENABLED:-0}
```

Add to `.env.example`:

```env
CAMREC_HIK_ENABLED=0
HIK_SDK_DIR=./hik-sdk-runtime
```

Do not change frontend/OpenList topology.

### Step 4: Run GREEN and Compose config checks

```bash
cd backend
uv run python -m pytest tests/test_hik_deploy_contract.py -q
cd ..
docker compose config
docker compose --profile hik config
```

Expected:

- test passes;
- both Compose configs parse;
- default config does not require proprietary SDK files to parse.

### Step 5: Commit

```bash
git add docker-compose.yml .env.example backend/tests/test_hik_deploy_contract.py
git commit -m "feat: make hik bridge a compose profile"
```

---

## Task 4: Refactor deploy.sh into core-first + optional HIK stage

**Files:**
- Modify: `deploy.sh`
- Modify: `backend/tests/test_hik_deploy_contract.py`

### Step 1: Add RED deploy-state contract tests

Extend `test_hik_deploy_contract.py` to lock down these implementation contracts:

- `.env` creation/normalization ensures `CAMREC_HIK_ENABLED=0` when absent;
- only `0` and `1` are accepted; invalid values fail clearly;
- disabled mode stores deterministic HIK state/hash as `disabled` and does not require executing `hik_sdk_hash`;
- HIK-specific Compose operations use `docker compose --profile hik` (separate command/array is acceptable);
- disabling removes stale `hik-bridge` with profile-scoped `rm -sf` or equivalent;
- `hik-sdk-runtime/*` only schedules HIK update when HIK is enabled;
- application-only backend changes do not force HIK restart;
- shared-image inputs that affect the bridge (at minimum `backend/Dockerfile`, backend dependency/lock inputs used by the image, `.dockerignore`, and `hik_bridge/*`) schedule bridge recreation only when HIK is enabled;
- state file records `hik_enabled` so `0 -> 1` / `1 -> 0` transitions are observable;
- core `up` occurs independently of the optional HIK stage;
- HIK health/runtime failure happens after the core stage and exits non-zero without issuing a core rollback/down.

Keep assertions structural enough to permit shell refactoring, but specific enough that the disabled path cannot accidentally hash/check SDK runtime.

### Step 2: Run RED + syntax

```bash
cd backend
uv run python -m pytest tests/test_hik_deploy_contract.py -q
cd ..
bash -n deploy.sh
```

Expected: contract failures against the current always-HIK deploy logic; shell syntax remains valid.

### Step 3: Implement flag loading and state

In `deploy.sh`:

- ensure `.env` contains `CAMREC_HIK_ENABLED=0`;
- parse and validate exactly `0|1` into `HIK_ENABLED`;
- read previous `hik_enabled` from deploy state;
- set current SDK hash to `disabled` without calling `hik_sdk_hash` when disabled;
- only resolve/validate `HIK_SDK_DIR`, `libhcnetsdk.so`, and `HCNetSDKCom/` when enabled.

### Step 4: Refactor change classification

Preserve existing incremental behavior but gate HIK execution:

- `frontend/*`: frontend only;
- ordinary `backend/app/*`, tests, migrations: backend only unless a file is an actual bridge image/runtime input;
- `backend/Dockerfile`, dependency/lock inputs copied into the shared core image, `.dockerignore`: rebuild shared image; if HIK enabled, mark bridge recreation;
- `hik_bridge/*`: shared image build + HIK update only when enabled;
- `hik-sdk-runtime/*`: HIK update only when enabled;
- docs/scripts that do not affect runtime remain no-restart unless existing policy already requires otherwise.

When code structure makes exact classification ambiguous, follow actual `backend/Dockerfile` COPY/install inputs, not filename intuition.

### Step 5: Separate core and HIK execution stages

Use two conceptual Compose commands:

```bash
COMPOSE=(docker compose)
HIK_COMPOSE=(docker compose --profile hik)
```

Core stage:

- build/update requested core services without profile dependency;
- wait for core health as currently required.

Disabled stage:

- if bridge exists or previous state was enabled, run profile-scoped stop/remove for `hik-bridge`;
- do not health-check bridge.

Enabled stage, after core succeeds:

- validate runtime;
- perform required shared-image build/reuse;
- start/recreate `hik-bridge` with `HIK_COMPOSE` when first enabled, image input changed, bridge code changed, SDK hash changed, or bridge is absent;
- wait for bridge health;
- on failure, print an actionable HIK error and exit non-zero **without stopping healthy core services**.

Persist successful deploy state only according to the existing baseline semantics; ensure `hik_enabled` and the current HIK hash/state are recorded consistently.

### Step 6: Run GREEN

```bash
cd backend
uv run python -m pytest tests/test_hik_deploy_contract.py -q
cd ..
bash -n deploy.sh
```

If Docker is available locally/CI, also run:

```bash
CAMREC_HIK_ENABLED=0 ./deploy.sh --check-only --no-ffmpeg-download
```

Expected: disabled planning succeeds without HCNetSDK runtime.

### Step 7: Commit

```bash
git add deploy.sh backend/tests/test_hik_deploy_contract.py
git commit -m "feat: deploy hik as an optional stage"
```

---

## Task 5: Update CI smoke, operator docs, and Phase 4 status

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/HIK_SDK_RUNTIME.md`
- Modify: `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-migration.md`
- Modify: `docs/superpowers/specs/2026-09-17-hik-optional-deployment-design.md` only if final status/verification record belongs there

### Step 1: Change CI Docker smoke to prove default core-only deployment

Update the Docker job to:

1. validate scripts;
2. run `docker compose config`;
3. run `docker compose --profile hik config` as profile syntax/config validation;
4. assert default `docker compose config --services` does not include `hik-bridge`;
5. build/start backend + frontend (and existing required core dependencies) with no HIK enable flag and no SDK runtime;
6. assert `camera-recorder-hik-bridge` is not running/created by core startup;
7. wait only for backend/frontend/core health;
8. preserve database migration compatibility checks;
9. verify backend is internal-only;
10. call backend `/api/camera-adapters` and assert `hik_sdk.available == false` with deployment-disabled reason;
11. keep HIK bridge unit tests in backend-quality fake/no-runtime mode;
12. remove the public-CI requirement to call bridge `/health` in core-only smoke;
13. cleanup both default and profile resources defensively at the end (`docker compose down -v` plus profile cleanup if needed).

Do not introduce proprietary SDK binaries into CI.

### Step 2: Update documentation

README deployment section:

- state that HIK SDK is disabled by default;
- normal users need no SDK runtime;
- to enable, set `CAMREC_HIK_ENABLED=1` and `HIK_SDK_DIR=...`, then run normal `./deploy.sh`;
- operators do not pass Compose profile flags manually.

`docs/HIK_SDK_RUNTIME.md`:

- replace the old assumption that the bridge always starts;
- document default-off, runtime directory shape, enable/disable behavior, `1 -> 0` bridge removal, and troubleshooting capability endpoint.

Migration/status doc:

- mark Phase 4 optional deployment complete only after exact-head CI is green;
- record the final validation run/SHA at closeout, not before.

### Step 3: Create/open Draft PR and run full CI

If the Draft PR was not already opened for RED evidence, create it now against `main`.

Final verification must be on the exact final head and include:

- backend quality/Ruff;
- all four backend pytest shards;
- HIK bridge fake/no-runtime tests;
- Docker core-only smoke;
- profile config validation;
- DB migration compatibility;
- frontend job only if workflow/path classification triggers it.

Do not claim completion from an earlier head.

### Step 4: Handle failures by category

- Expected new-test RED -> implement current task.
- Unexpected regression -> invoke `superpowers:systematic-debugging` before patching.
- CI infrastructure/flaky behavior -> prove root cause before retry/change.

### Step 5: Final self-review

Invoke `superpowers:requesting-code-review`. If no reviewer subagent is available, perform equivalent review over `main...HEAD` and verify:

- no HIK bridge request when disabled;
- no persisted `offline/failed` state caused solely by capability unavailability;
- unified HIK create/edit still persists while disabled;
- core Compose has no dependency on HIK;
- deploy default does not hash/check SDK runtime;
- `1 -> 0` removes only HIK bridge;
- HIK failure cannot stop/rollback core;
- no credentials in errors/logs;
- no data migration added unnecessarily;
- PR has no unresolved review threads/comments.

### Step 6: Merge using established repository workflow

After exact-head CI is green and review is clean:

- update PR description with final scope + exact CI evidence;
- mark PR ready;
- squash merge to `main` (unless repository settings force another supported method);
- verify PR `merged=true` and remote `main` points at returned merge SHA;
- inspect post-merge push CI and report its current/final state.

No additional merge confirmation is required because the user has already established the preference to merge completed, green work directly.
