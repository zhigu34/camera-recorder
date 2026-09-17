# HIK Optional Deployment Design

Status: **Approved for implementation**

Date: 2026-09-17

## Goal

Make Hikvision HCNetSDK support a truly optional deployment capability rather than a core runtime dependency.

Core Camera Recorder must start, remain healthy, and support manual RTSP and ONVIF when HIK is disabled or unavailable. Existing `hik_sdk` camera configuration must be preserved without forcing bridge startup, SDK runtime validation, or background device access.

This is Phase 4 of the Camera Architecture Refactor.

## Confirmed Decisions

### 1. Default deployment state

HIK is disabled by default.

```env
CAMREC_HIK_ENABLED=0
HIK_SDK_DIR=./hik-sdk-runtime
```

`CAMREC_HIK_ENABLED=0` is authoritative. Presence of an SDK directory MUST NOT implicitly enable HIK.

Only explicit `CAMREC_HIK_ENABLED=1` enables HIK deployment behavior.

### 2. Deployment topology

Core services:

```text
backend
frontend
openlist
```

Optional HIK adapter service:

```text
hik-bridge + HCNetSDK runtime
```

`docker-compose.yml` MUST put `hik-bridge` under:

```yaml
profiles:
  - hik
```

The backend MUST NOT depend on `hik-bridge` through Compose `depends_on`.

Backend startup and backend health MUST succeed when the HIK profile is absent.

`CAMREC_HIK_BRIDGE_URL` may continue to default to the internal bridge URL, but code MUST only attempt to use that URL when HIK capability is enabled and required.

### 3. Deploy script behavior

`deploy.sh` must translate the explicit HIK flag into Compose behavior so operators never need to remember raw profile arguments.

#### HIK disabled

When `CAMREC_HIK_ENABLED=0`:

- do not add `--profile hik` to normal Compose operations;
- do not require `HIK_SDK_DIR` to exist;
- do not validate `libhcnetsdk.so` or `HCNetSDKCom/`;
- do not calculate a real HIK runtime hash;
- do not build/start/restart/health-check `hik-bridge`;
- do not fail deployment because HIK runtime or bridge is absent;
- HIK-related source/runtime changes may be detected for informational purposes but must not force HIK deployment.

Deployment state should represent disabled HIK deterministically, for example with an internal state value such as `disabled`, rather than interpreting a missing SDK directory as a deployment failure.

#### HIK enabled

When `CAMREC_HIK_ENABLED=1`:

- automatically use the `hik` Compose profile;
- validate the configured SDK runtime directory before bridge deployment;
- require `libhcnetsdk.so` and `HCNetSDKCom/`;
- calculate the HIK runtime hash;
- build/start/restart `hik-bridge` when needed;
- wait for bridge health after deployment;
- prefer restarting only `hik-bridge` when only the SDK runtime changed.

A HIK-specific deployment failure must produce an actionable error, but HIK must not become a Compose startup prerequisite for backend/frontend/openlist.

### 4. Disabling an already running bridge

Changing configuration from:

```text
CAMREC_HIK_ENABLED=1
```

to:

```text
CAMREC_HIK_ENABLED=0
```

must actively stop and remove the existing `hik-bridge` container.

The deployment script MUST NOT merely omit the HIK profile on the next `up`, because that would leave an already running bridge unmanaged.

Equivalent behavior to the following is acceptable:

```bash
docker compose --profile hik rm -sf hik-bridge
```

The removal must be scoped to the optional HIK service and must not stop core services.

### 5. Incremental deployment classification

Existing incremental deployment behavior is preserved, with HIK-aware gating.

Expected classification:

- `frontend/*`: frontend only; never touches HIK.
- ordinary backend changes: rebuild/update backend; HIK update only if the shared image truly requires refresh and HIK is enabled.
- `hik_bridge/*`: if HIK enabled, rebuild the required image and update bridge; if disabled, do not deploy bridge.
- `hik-sdk-runtime/*`: if HIK enabled, update bridge only; if disabled, ignore for deployment execution.
- documentation-only changes: no service restart.
- `.env` transition `0 -> 1`: validate runtime and start HIK profile.
- `.env` transition `1 -> 0`: remove existing bridge and leave core running.

HIK-disabled planning MUST not hash or validate the proprietary runtime merely to determine a deployment plan.

### 6. Backend deployment configuration

Add a deployment setting:

```python
settings.hik_enabled: bool = False
```

It is loaded from:

```text
CAMREC_HIK_ENABLED
```

The backend container receives the value explicitly from Compose:

```yaml
CAMREC_HIK_ENABLED: ${CAMREC_HIK_ENABLED:-0}
```

This is deployment configuration, not a mutable SQLite/UI setting.

### 7. Adapter capability semantics

`GET /api/camera-adapters` remains the canonical capability source.

HIK availability is resolved in two layers.

#### HIK disabled by deployment configuration

When `settings.hik_enabled` is false:

```json
{
  "id": "hik_sdk",
  "label": "Hikvision SDK",
  "available": false,
  "unavailable_reason": "HIK SDK adapter is disabled by deployment configuration"
}
```

The registry MUST NOT attempt a bridge `/health` request in this state.

#### HIK enabled

When `settings.hik_enabled` is true, query bridge `/health`.

HIK is available only when:

- the bridge HTTP request succeeds; and
- bridge health reports `runtime_available=true`.

A reachable bridge with missing/unloadable HCNetSDK runtime is still unavailable.

Bridge failures or runtime-unavailable details should be surfaced in a sanitized `unavailable_reason`.

`manual_rtsp` and `onvif` remain independent of HIK state.

### 8. Existing HIK camera preservation

Disabling HIK MUST NOT mutate persisted camera configuration.

For an existing `hik_sdk` Camera, preserve:

- `Camera.id`;
- `CameraConnection.id`;
- adapter selection;
- encrypted credentials;
- connection revision;
- HIK adapter config;
- discovery/device cache;
- historical recordings/events/health data.

Do not automatically switch adapters and do not increment revision merely because deployment capability changed.

Connection configuration remains editable while HIK is unavailable. The user may later re-enable HIK or explicitly switch the Camera to another adapter through the normal unified mutation path.

### 9. Adapter-unavailable is not connectivity-offline

Do not overload `connectivity_status=offline` to represent deployment capability.

`offline` means an enabled adapter/device was attempted and could not be reached.

`adapter_unavailable` means the selected adapter cannot operate in the current deployment.

No new database status column is required for Phase 4.

The UI can derive deployment availability from:

```text
Camera.connection.adapter
+
GET /api/camera-adapters
```

Phase 5 will render `adapter_unavailable` as a distinct operational state.

### 10. Runtime coordination

Extend runtime restoration semantics so an enabled Camera using an unavailable adapter does not restart device-access workers.

Conceptually:

```text
CameraRuntimeCoordinator.restore(camera_id)
  -> missing
  -> disabled
  -> adapter_unavailable
  -> running
```

Before restoring recorder, schedule-owned device activity, motion detection, or event pre-roll, the coordinator checks whether the Camera's current adapter is available.

If the current adapter is unavailable:

- do not start recorder;
- do not start motion detection;
- do not start event pre-roll/device-access workers;
- do not create HIK bridge streams;
- return `adapter_unavailable`.

`stop_all()` behavior remains unchanged and continues to tear down active media sessions first.

### 11. Connectivity monitor behavior

The connectivity monitor MUST NOT probe HIK through the bridge when HIK capability is disabled/unavailable.

For an enabled `hik_sdk` Camera whose adapter is unavailable:

- skip HIK bridge network calls;
- do not increment device connectivity failures merely because the adapter is unavailable;
- do not rewrite persisted connectivity state to `offline` for this reason;
- keep capability state separate from device connectivity history.

Manual RTSP and ONVIF connectivity behavior remains unchanged.

### 12. HIK media and probe guards

When HIK is disabled/unavailable, endpoints or services that explicitly require HIK runtime must fail fast without attempting bridge network access.

This includes at minimum:

- persisted HIK camera probe;
- draft HIK connection probe;
- internal HIK media/stream startup.

The response should be an explicit unavailable/service error (HTTP 503 at API boundaries where appropriate), with no password or credential leakage.

Saving/editing HIK connection configuration is still allowed because Phase 3 intentionally separated persistence from verification/runtime availability.

### 13. Error boundaries

Core deployment success and HIK capability success are separate concerns.

Expected behavior:

- HIK disabled: missing SDK is normal and produces no deployment failure.
- HIK enabled + invalid runtime: HIK deployment fails with a clear runtime validation message.
- HIK enabled + bridge unhealthy: capability reports unavailable and HIK-specific operations fail; core backend remains independently startable.
- bridge disabled after previously running: bridge is explicitly removed, not left running.
- existing HIK Camera: configuration persists regardless of deployment state.

There is no automatic fallback from `hik_sdk` to RTSP/ONVIF.

## Compose Design

Target structure:

```yaml
services:
  hik-bridge:
    profiles: ["hik"]
    # existing bridge runtime/image/health configuration

  backend:
    # no depends_on: hik-bridge
    environment:
      CAMREC_HIK_ENABLED: ${CAMREC_HIK_ENABLED:-0}
      CAMREC_HIK_BRIDGE_URL: http://hik-bridge:8100
```

Frontend and OpenList dependency structure stays unchanged.

## Deployment State Machine

```text
                    CAMREC_HIK_ENABLED
                    /                 \
                  0                     1
                  |                     |
          core compose only       enable profile hik
                  |                     |
       no SDK check/hash          validate SDK runtime
                  |                     |
       no bridge health            hash runtime
                  |                     |
       HIK unavailable             start/update bridge
                  |                     |
       remove stale bridge         wait for health
                                        |
                              registry checks runtime_available
```

No implicit transition is driven by filesystem presence.

## Testing Strategy

### Backend tests

Cover:

- `settings.hik_enabled` defaults to false;
- adapter registry performs no bridge health call while disabled;
- enabled + healthy bridge + `runtime_available=true` => HIK available;
- enabled + healthy HTTP but `runtime_available=false` => HIK unavailable;
- enabled + bridge error => HIK unavailable with sanitized reason;
- RuntimeCoordinator returns `adapter_unavailable` without restoring device workers;
- connectivity monitor skips bridge probing for unavailable HIK cameras;
- HIK draft/persisted probe fails fast when disabled;
- HIK media startup fails fast when disabled;
- HIK Camera connection data and revision are untouched by capability state changes.

### Deploy-script tests

Add shell/static tests that verify:

- default flag is disabled;
- disabled planning does not require SDK runtime;
- disabled planning does not calculate the SDK runtime hash;
- enabled planning requires SDK runtime validation;
- enabled Compose operations include `--profile hik`;
- `1 -> 0` removes an existing HIK bridge;
- SDK runtime-only changes update only HIK when enabled;
- SDK runtime-only changes are ignored for deployment execution when disabled;
- ordinary core changes remain deployable with no HIK runtime present.

### Compose / CI smoke

Public CI has two layers.

#### Core-only smoke

With no HIK enable flag set:

- default is equivalent to `CAMREC_HIK_ENABLED=0`;
- default active Compose services exclude `hik-bridge`;
- backend/frontend/openlist start without a proprietary SDK runtime;
- backend health succeeds;
- adapter registry reports HIK unavailable.

#### HIK profile configuration smoke

Without proprietary runtime binaries:

- `docker compose --profile hik config` is valid;
- bridge unit tests continue using fake/no-runtime SDK boundaries;
- public CI does not require a real HCNetSDK installation.

A real HCNetSDK integration smoke remains an environment-specific/private validation.

## Documentation

Update:

- `.env.example` to make `CAMREC_HIK_ENABLED=0` explicit;
- README/deployment docs to explain how to enable HIK;
- migration/status documentation to mark Phase 4 complete only after final CI passes.

Operator enablement remains:

```env
CAMREC_HIK_ENABLED=1
HIK_SDK_DIR=/path/to/hik-sdk-runtime
```

followed by the normal command:

```bash
./deploy.sh
```

Operators do not manually pass Compose profile flags.

## Scope

Included:

- optional HIK Compose profile;
- explicit default-off deployment flag;
- HIK-aware deploy planning and stale bridge removal;
- backend capability gating;
- runtime/connectivity/media/probe guards for unavailable HIK;
- core-only public CI smoke;
- HIK profile configuration smoke;
- deployment documentation.

Not included:

- Camera management UI split-view work;
- UI adapter selector redesign beyond consuming the existing capability contract;
- automatic adapter fallback;
- automatic vendor/SDK detection;
- bundling proprietary HCNetSDK binaries in the repository;
- HIK event/alarm/PTZ features;
- data-model migrations unrelated to deployment capability.

## Acceptance Criteria

Phase 4 is complete when all of the following are true:

1. A fresh default deployment with no HIK SDK runtime starts backend/frontend/openlist successfully.
2. Default Compose operation does not start `hik-bridge`.
3. `CAMREC_HIK_ENABLED=1` automatically activates the `hik` profile through `deploy.sh`.
4. HIK enabled deployment validates the configured runtime and bridge health.
5. Switching from enabled to disabled removes the running bridge without stopping core services.
6. Backend adapter capability reports disabled/unhealthy HIK accurately without affecting RTSP/ONVIF.
7. Existing HIK Camera configuration remains intact while HIK is unavailable.
8. Runtime/background workers do not access the bridge when HIK is unavailable.
9. Public CI proves core-only deployment without proprietary SDK binaries.
10. Existing backend, HIK fake-runtime, migration, Docker, and frontend regression suites remain green.
