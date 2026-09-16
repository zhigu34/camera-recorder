# Camera Architecture Refactor Design

Status: **Draft — confirmed sections are implementation-ready; migration sequencing still under discussion**

Date: 2026-09-16

## Goal

Refactor camera management so `camera.id` is a stable monitoring-point identity. Connection configuration and adapter choice may change without breaking recordings, events, health history, or statistics. Camera disablement must stop all active/background access. Permanent deletion is allowed only for cameras with no meaningful history.

## Confirmed decisions

### 1. Camera identity semantics

`Camera.id` represents the monitoring point, not a specific hardware unit or connection configuration.

The following operations MUST keep the same `camera.id`:

- change IP/host
- change credentials
- change RTSP paths/ports
- switch adapter (`manual_rtsp` / `onvif` / `hik_sdk`)
- replace the physical camera at the same monitoring point
- change manufacturer/model/serial metadata

Historical recordings, events, motion events, health samples and statistics remain associated with the same camera ID.

### 2. Disable semantics

Do not introduce an archive state. Existing `Camera.enabled` becomes the authoritative runtime master switch.

When `enabled=false`, the system MUST:

- stop active recording
- stop schedule-owned recording state
- stop motion-detection workers
- stop event pre-roll/ring-buffer workers
- release adapter sessions/streams (including HIK bridge streams)
- exclude the camera from background connectivity probing
- prevent automatic reconnect/restart
- reject manual recording start/restart
- reject live preview/stream startup that would connect to the device

Explicit one-shot connection testing from the edit flow is still allowed while disabled.

Re-enabling the camera keeps the same camera ID and restores runtime components according to saved policies.

### 3. Permanent delete semantics

Permanent deletion is for accidental/test cameras only.

A camera may be hard-deleted only when it has no meaningful historical records. The UI MUST show deletion impact before permanent deletion.

Historical records that block deletion include at minimum:

- recordings
- motion events
- camera health samples
- business/alert events that represent actual monitoring history

Configuration records do NOT block deletion and may cascade with the Camera when hard deletion is allowed:

- current connection configuration
- adapter-specific connection configuration
- motion detection settings
- motion zones
- other current policy/configuration rows

System/audit lifecycle events such as camera creation, config changes, adapter changes, probe success/failure, enable/disable MUST NOT make a test camera undeletable. If the Camera is deleted, such audit records may remain with `camera_id` cleared while retaining non-secret textual metadata.

There MUST NOT be a user-facing "delete camera and all history" shortcut.

Suggested API:

`GET /api/cameras/{id}/deletion-impact`

Example shape:

```json
{
  "deletable": false,
  "camera_id": 12,
  "blockers": {
    "recordings": 326,
    "motion_events": 18,
    "health_samples": 2814,
    "business_events": 41
  },
  "derived": {
    "pending_uploads": 3
  }
}
```

### 4. Historical foreign-key protection

Historical rows MUST NOT use `ON DELETE CASCADE` from Camera.

Change camera-history foreign keys to `RESTRICT` / `NO ACTION` (or equivalent SQLite-safe protection), including at minimum:

- `recordings.camera_id`
- `motion_events.camera_id`
- `camera_health_samples.camera_id`

The API deletion-impact check is the first protection layer; database FK restrictions are the final safety layer.

Current configuration rows may continue to use `ON DELETE CASCADE`.

### 5. Data model split

`Camera` becomes the stable monitoring-point record plus runtime policy/state.

Recommended structure:

```text
Camera
├─ id                         stable monitoring-point ID
├─ name
├─ manufacturer               current physical-device metadata
├─ model
├─ form_factor
├─ enabled                    runtime master switch
├─ auto_record
├─ recording_schedule_*
├─ timestamp_mode
├─ status / last_probe_at / last_online_at
└─ media capability cache     codec / resolution / fps / etc.

CameraConnection
├─ id
├─ camera_id                  UNIQUE: one current connection per Camera
├─ adapter                    manual_rtsp | onvif | hik_sdk
├─ host
├─ username
├─ password_encrypted
├─ revision
├─ verification_status        unverified | verified | failed
├─ verified_at
├─ last_error
└─ updated_at

RtspConnectionConfig
├─ connection_id
├─ port
├─ main_path
└─ sub_path

OnvifConnectionConfig
├─ connection_id
├─ device_service_url
├─ device_uuid
├─ recording_profile_token
├─ preview_profile_token
├─ detection_profile_token
├─ profiles/cache
└─ discovered stream URI cache

HikConnectionConfig
├─ connection_id
├─ sdk_port
├─ channel
├─ main_stream_type
├─ sub_stream_type
├─ device_serial
├─ device_name
└─ device type/model cache
```

Each camera has exactly one current connection. Do not support simultaneous active/candidate/fallback connections.

Old passwords and complete old connection objects MUST NOT be retained as history. Audit only non-secret summaries such as adapter and endpoint changes.

### 6. Connection editing and adapter switching

Connection edits may be saved even if validation fails or the device is currently offline.

Connection state records verification separately:

- `unverified`
- `verified`
- `failed`

Connection test is optional before save.

Adapter switching MUST NOT create a new Camera. Examples:

- RTSP -> ONVIF
- ONVIF -> HIK SDK
- HIK SDK -> RTSP

All keep the same `camera.id`.

Every connection change increments `CameraConnection.revision`. Long-running workers must not continue reconnecting with stale connection revisions.

### 7. Runtime coordination

Introduce a single runtime orchestration service, tentatively `CameraRuntimeCoordinator`.

API handlers MUST stop manually coordinating Recorder/Motion/Event workers independently.

Required conceptual operations:

```text
stop_all(camera_id)
reload(camera_id)
```

`stop_all` stops all device-access runtime components.

`reload`:

1. stops all workers using the old connection
2. releases adapter-specific temporary sessions/resources
3. reloads current Camera + CameraConnection
4. exits if Camera is disabled
5. exits with explicit adapter-unavailable state if the selected adapter capability is unavailable
6. otherwise restores connectivity monitoring, motion/event workers and recording policy
7. schedule-owned recording is reconciled by the schedule manager
8. a previously manual-running recorder may be restarted with the new connection

This centralizes lifecycle behavior for IP changes, credential changes, channel changes, adapter switches and physical-device replacement.

### 8. Unified camera API direction

Remove adapter-specific create/edit semantics from the frontend-facing API.

Target public API direction:

- `POST /api/cameras` — create monitoring point + current connection
- `PUT/PATCH /api/cameras/{camera_id}` — edit point metadata/policies and/or current connection
- `POST /api/camera-connections/probe` (final path TBD) — one-shot adapter-aware connection test without persistence
- `GET /api/cameras/{camera_id}/deletion-impact`
- `DELETE /api/cameras/{camera_id}` — only succeeds when deletion impact has no blockers

Adapter-specific implementation modules remain internal services; the UI should not need separate ONVIF/HIK creation endpoints.

### 9. Adapter capability registry

Adapter availability is a backend capability, not a frontend assumption.

Add a capability endpoint such as:

`GET /api/camera-adapters`

Each adapter reports at minimum:

- id
- label
- available
- optional unavailable reason

Expected behavior:

- `manual_rtsp`: built-in, normally available
- `onvif`: built-in, normally available
- `hik_sdk`: depends on optional HIK bridge/runtime

Unavailable adapters remain visible but disabled in the UI with an explanatory reason; do not hide them.

If an existing Camera uses an adapter that later becomes unavailable, preserve Camera and connection configuration, stop device-access workers, expose `adapter_unavailable`, and allow the user to switch to another adapter.

### 10. HIK bridge becomes truly optional

HIK is an optional adapter capability, not a core deployment dependency.

Target deployment model:

```text
Core:
- backend
- frontend
- openlist

Optional adapter service:
- hik-bridge + HCNetSDK runtime
```

Compose:

- put `hik-bridge` under profile `hik`
- remove backend `depends_on: hik-bridge`
- backend MUST start and be healthy without HIK

Deployment configuration:

```text
CAMREC_HIK_ENABLED=0|1
HIK_SDK_DIR=...
```

`deploy.sh` should automatically enable the compose profile when `CAMREC_HIK_ENABLED=1`; normal users should not need to remember raw compose profile flags.

When HIK is disabled:

- do not require SDK runtime
- do not hash/check HIK runtime
- do not build/start/health-check hik-bridge
- do not fail deployment because HIK is absent

When enabled:

- validate runtime
- run HIK bridge
- restart only HIK bridge when runtime changes where possible
- health-check bridge and expose capability state to backend/frontend

### 11. Camera management page — permanent split view

The camera management page uses a desktop split layout rather than a temporary drawer.

```text
┌──────────────────────┬──────────────────────────────────────────────┐
│ Camera card list     │ Selected camera detail                      │
│                      │                                              │
│ [search/filter]      │ Warehouse East Gate                    #12  │
│ ┌──────────────────┐ │ online · recording                           │
│ │ Warehouse East   │ │                                              │
│ │ ONVIF · online   │ │ live preview                                 │
│ └──────────────────┘ │                                              │
│ ┌──────────────────┐ │ device / connection / policy / history      │
│ │ Warehouse West   │ │                                              │
│ │ RTSP · disabled  │ │ actions                                      │
│ └──────────────────┘ │                                              │
└──────────────────────┴──────────────────────────────────────────────┘
```

The existing camera-detail drawer behavior is conceptually retained but rendered permanently in the right pane.

Requirements:

- left pane: card list, search, filter, sort, quick status
- right pane: persistent selected-camera detail
- preserve `?camera_id=<id>` deep linking
- clicking a card updates `camera_id` and right-pane content
- page refresh with a valid `camera_id` restores that camera selection
- if there is no `camera_id`, select the first visible camera when appropriate
- if there are no cameras, the right pane shows an empty-state Add Camera CTA
- no overlay drawer is used on normal desktop width
- narrow/mobile layouts may collapse to list -> detail navigation responsively, but desktop remains split view

Recommended desktop sizing:

- left pane fixed/limited width around 320–380 px
- right pane flexible width
- left list scrolls independently
- right detail scrolls independently where practical
- keep preview area visible near the top of the right pane

### 12. Camera card information hierarchy

Each left-side card shows only high-value operational information:

```text
Warehouse East Gate                         #12
Hikvision DS-xxxx · bullet
ONVIF · 192.168.1.20
online · recording
```

The card must show current connection adapter and endpoint from `CameraConnection`, not legacy RTSP-centered Camera fields.

Distinct operational states:

- `disabled`: intentional state, not an error
- `offline`: enabled but unreachable
- `unverified`: saved connection has not succeeded yet
- `adapter_unavailable`: selected adapter capability is unavailable in this deployment
- recording/runtime error: device may be online but runtime is unhealthy

Summary/filter cards should include Disabled separately rather than counting disabled devices as connection issues.

### 13. Right-side camera detail information architecture

The right pane is organized in this order:

1. identity + current high-level status
2. live preview
3. current device information
4. current connection
5. runtime/recording policy
6. history summary and deep links
7. device management actions
8. dangerous permanent-delete action

Example:

```text
Warehouse East Gate                                  #12
online · recording

[ live preview ]

Device
Hikvision · DS-xxxx · bullet
serial ABC123                                      [Edit]

Connection
ONVIF · verified
192.168.1.20
last verified 2026-09-16 14:32              [Edit connection]

Runtime policy
enabled · auto recording · motion enabled          [Edit]

History
recordings 326          [View]
motion events 18        [View]
other events 41         [View]
health samples 2814     [View]

Device management
[Disable camera]

Danger zone
[Delete camera]
```

Do not create a separate "replace device" workflow. Physical replacement is represented as normal device-metadata + current-connection editing and recorded through a non-secret audit summary.

### 14. Unified add/edit experience

Remove separate RTSP / ONVIF / HIK add buttons and standalone add modals.

The page has one primary `Add Camera` action.

Use one reusable `CameraEditorDialog` rather than a long multi-step wizard. Organize it into sections:

- monitoring-point/device information
- adapter selection
- adapter-specific connection fields
- optional connection test/discovery and result
- runtime/recording policy

Adapter selection is driven by `GET /api/camera-adapters`.

Changing adapter dynamically swaps only the connection-fields section.

The same editor is reused for existing cameras. Switching adapter explicitly summarizes old -> new connection and states that Camera ID/history remain unchanged.

Unavailable adapters are visible but not selectable, with their unavailable reason.

Connection test is optional; save is allowed when offline/unverified.

### 15. Disable interaction

Do not expose `enabled` as an easy-to-toggle list switch.

Disabling has runtime impact and requires a confirmation explaining that recording, probing, reconnect, motion detection and event pre-roll will stop while history remains intact.

The disabled camera remains visible in the left list and can be re-enabled from the right detail pane.

### 16. Delete interaction

Permanent delete lives only in the right-pane Danger Zone; do not place a one-click trash icon on camera cards.

Before delete, fetch deletion impact.

When blockers exist, show counts and deep links to the corresponding history screens, plus an optional Disable action. Do not offer cascade deletion of history.

When blockers are zero, require explicit permanent-delete confirmation and delete configuration rows together with the empty/test Camera.

## Implementation backlog

### Phase 1 — Database safety and domain model

- [ ] Add `CameraConnection`
- [ ] Add RTSP connection config model
- [ ] Refactor/migrate ONVIF metadata to connection-scoped config
- [ ] Refactor/migrate HIK metadata to connection-scoped config
- [ ] Add connection revision + verification state
- [ ] Migrate existing Camera connection fields into `CameraConnection`
- [ ] Keep compatibility reads only for migration window if needed
- [ ] Change historical Camera FKs away from `ON DELETE CASCADE`
- [ ] Add deletion-impact service/query
- [ ] Classify Event rows into blocking business history vs non-blocking audit/lifecycle events
- [ ] Add migration tests protecting existing camera IDs/history

### Phase 2 — Runtime lifecycle

- [ ] Introduce `CameraRuntimeCoordinator`
- [ ] Centralize stop/reload behavior
- [ ] Enforce `enabled=false` across all workers and manual start/restart paths
- [ ] Reject preview/device access for disabled cameras except explicit one-shot probe
- [ ] Ensure connection revision invalidates stale workers
- [ ] Refactor connectivity monitor to load `CameraConnection`
- [ ] Refactor recorder stream resolution to load current connection
- [ ] Refactor motion/event pre-roll workers to load current connection
- [ ] Add adapter-unavailable runtime state
- [ ] Add lifecycle/concurrency tests for adapter switch while recording/detecting

### Phase 3 — Unified adapter API

- [ ] Add adapter capability registry + API
- [ ] Add unified adapter-aware probe endpoint
- [ ] Refactor create camera API to accept a connection object
- [ ] Refactor update camera API to support same-adapter edits and adapter switching
- [ ] Deprecate frontend use of dedicated ONVIF/HIK create/update endpoints
- [ ] Keep adapter-specific probe/discovery logic as internal service modules
- [ ] Add structured deletion-impact endpoint
- [ ] Make DELETE reject blockers without deleting history
- [ ] Add non-secret audit records for adapter/device changes

### Phase 4 — HIK optional deployment

- [ ] Add `hik` compose profile
- [ ] Remove backend dependency on hik-bridge
- [ ] Add `CAMREC_HIK_ENABLED`
- [ ] Make deploy planning conditional on HIK enabled state
- [ ] Skip runtime hash/check/health when HIK disabled
- [ ] Ensure HIK failure cannot block core deployment
- [ ] Surface bridge/runtime availability through adapter registry
- [ ] Update HIK deployment documentation

### Phase 5 — Camera management split-view UI

- [ ] Replace desktop drawer with permanent left-list/right-detail split view
- [ ] Preserve `camera_id` deep links and selection restoration
- [ ] Make left camera list independently scrollable
- [ ] Make right detail pane the persistent camera workspace
- [ ] Add empty state when no camera exists
- [ ] Add separate Disabled summary/filter state
- [ ] Show adapter + connection endpoint on each card
- [ ] Replace three add entry points with one Add Camera action
- [ ] Introduce reusable `CameraEditorDialog`
- [ ] Add adapter selector driven by capability API
- [ ] Render adapter-specific fields inside the shared editor
- [ ] Support optional probe/discovery before save
- [ ] Support connection edits without changing Camera ID
- [ ] Support explicit adapter switching in existing Camera editor
- [ ] Make disabled state prominent and prevent runtime actions
- [ ] Add right-pane history summary/deep links
- [ ] Add deletion-impact dialog with deep links to blocking data
- [ ] Keep permanent Delete only in the right-pane Danger Zone
- [ ] Remove old HIK/ONVIF standalone add modals after migration
- [ ] Add responsive fallback from split view to list/detail navigation on narrow screens

## Remaining design discussion

The following are intentionally not finalized yet:

- database migration/compatibility strategy from the current Camera-centered connection fields
- rollout order that keeps the application usable between intermediate phases
- whether old adapter-specific API routes remain as short-lived compatibility wrappers or are removed in the same release
- exact event classification mechanism for blocking vs non-blocking deletion history
- final API request/response schemas and validation details

These should be resolved before implementation begins.
