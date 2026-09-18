# Camera Architecture Refactor — Migration Notes

Status: **Switch complete for manual RTSP + ONVIF + HIK; RuntimeCoordinator/media lifecycle, unified adapter API, optional HIK deployment, and Phase 5 camera-management UI convergence complete**

Date: 2026-09-16

## Current production data assumption

The current installation only contains cameras configured through the existing manual RTSP path.

Therefore the migration MUST treat existing persisted cameras as RTSP cameras and MUST NOT attempt to infer or manufacture historical ONVIF/HIK connection data.

ONVIF and HIK SDK remain supported target adapters after the refactor, but they are future/current selectable connection methods rather than legacy data that needs backfilling.

## Safe migration strategy

Use an Expand -> Switch -> Contract rollout.

Phase 1, the manual-RTSP/ONVIF/HIK Switch slice, the bounded RuntimeCoordinator lifecycle slice, the connection revision guard slice, the active media-session lifecycle slice, the Phase 3 unified adapter API slice, the Phase 4 optional HIK deployment slice, and the Phase 5 camera-management UI convergence completed items are checked below. Unchecked items remain deliberate follow-up work and are not implied by the completed slices.

### Expand

- [x] Create `camera_connections`.
- [x] Create `rtsp_connection_configs`.
- [x] Create an empty ONVIF connection-config table for the new architecture; do not backfill it from legacy rows.
- [x] Create the HIK connection-config table for the new architecture; do not backfill it from legacy rows.
- [x] For every existing Camera, create exactly one `CameraConnection` with `adapter=manual_rtsp`.
- [x] Copy existing `Camera.ip` -> `CameraConnection.host`.
- [x] Copy existing `Camera.username` -> `CameraConnection.username`.
- [x] Copy existing `Camera.password_encrypted` -> `CameraConnection.password_encrypted` without decrypting/re-encrypting it.
- [x] Set initial `CameraConnection.revision=1`.
- [x] Set initial verification state from current persisted connectivity/probe information where it is unambiguous; otherwise use `unverified` rather than guessing.
- [x] Copy `Camera.rtsp_port`, `Camera.rtsp_path`, and `Camera.sub_rtsp_path` into `RtspConnectionConfig`.
- [x] Preserve every existing `Camera.id` exactly.
- [x] Preserve all Recording/Event/Motion/Health references to existing `camera_id` values.
- [x] Change historical camera foreign keys from destructive cascade behavior to RESTRICT/NO ACTION-safe behavior.
- [ ] Before destructive SQLite table rebuild migrations, create a database backup/snapshot.
- [x] Add migration verification: every existing Camera must have exactly one current connection after backfill.
- [x] Add migration verification: every backfilled connection must be `manual_rtsp` for this installation.
- [x] If migration encounters a legacy Camera whose adapter is unexpectedly not `manual_rtsp`, abort migration with a clear error instead of guessing how to transform it.

### Switch

- [x] Make `CameraConnection` + adapter config the canonical persisted/runtime source for manual RTSP and ONVIF reads/writes.
- [x] Move HIK persistence/runtime reads to `CameraConnection` + an HIK adapter config.
- [x] Keep legacy Camera RTSP/auth fields temporarily as compatibility shadow fields for one rollback window.
- [x] During the rollback window, writes through the connection service mirror compatible RTSP endpoint/auth fields back to legacy Camera columns.
- [x] Existing RTSP cameras continue using the same Camera IDs and history after the switch.
- [x] New manual RTSP and ONVIF cameras are created with exactly one current connection.
- [x] New/updated ONVIF cameras persist connection-scoped profile/capability/credential-free URI caches and no longer write new `OnvifDeviceMetadata` state.
- [x] New HIK connections are created canonically in the new connection model; legacy HIK metadata remains only as a rollback shadow during the compatibility window.
- [x] Adapter switching among `manual_rtsp`, `onvif`, and `hik_sdk` updates the same Camera ID and current `CameraConnection` identity.
- [x] Expose one adapter capability registry for manual RTSP, ONVIF, and HIK SDK instead of hard-coding feature support in separate API surfaces.
- [x] Expose one discriminated nested `connection` contract in unified Camera reads and writes while keeping legacy flat manual RTSP fields during the compatibility window.
- [x] Use one adapter-aware draft Probe service for manual RTSP, ONVIF, and HIK SDK validation without persisting plaintext credentials or credential-bearing ONVIF URIs.
- [x] Use one generic create/update/switch mutation path with stable Camera and `CameraConnection` identity and exactly one revision increment for a real connection-target change.
- [x] Allow canonical ONVIF/HIK connections to be saved as `unverified` when an operator intentionally saves without a successful discovery/probe cache.
- [x] Probe the persisted current connection through the canonical adapter service; Probe may refresh verification/cache/media state but does not increment connection revision or mutate target credentials/settings.
- [x] The dedicated ONVIF API routes remain temporary wrappers over the unified mutation/probe services rather than an independent persistence path.
- [x] Convert dedicated HIK API/persistence paths into wrappers over the unified mutation/probe services.
- [x] Introduce `CameraRuntimeCoordinator` for recorder/schedule/motion/event-buffer stop/reload orchestration.
- [x] Route manual RTSP connection/policy edits, ONVIF re-discovery updates, and Camera deletion through the runtime coordinator.
- [x] Treat `Camera.enabled=false` as the runtime master switch for manual start, restart, and new preview requests while still allowing explicit one-shot Probe.
- [x] Preserve the event-buffer handoff invariant when manually starting normal recording by using `start_regular_recorder`.
- [x] Terminate already-active preview sessions when a Camera is disabled or reloaded.
- [x] Release adapter-specific temporary sessions on disable/reload, especially HIK bridge streams.
- [x] Add current-connection revision stale-worker invalidation inside long-running reconnect loops.

### Optional HIK deployment

- [x] Make HIK SDK support default-off with `CAMREC_HIK_ENABLED=0`.
- [x] Keep `hik-bridge` behind the Compose `hik` profile and remove it from core backend dependencies.
- [x] Keep manual RTSP, ONVIF, backend, frontend, and OpenList operational without proprietary HCNetSDK runtime files.
- [x] Use one canonical HIK capability guard across runtime restore, connectivity monitoring, Probe, and media startup.
- [x] Preserve persisted HIK connectivity state when the deployment capability is unavailable instead of rewriting the camera as offline or incrementing failure counters.
- [x] Keep canonical HIK configuration saveable as `unverified` while runtime capability is unavailable.
- [x] Refactor `deploy.sh` into a core-first stage plus an optional HIK stage, with `0 -> 1` / `1 -> 0` state tracking.
- [x] Do not inspect or hash the private HCNetSDK runtime when HIK is disabled.
- [x] Ensure an optional HIK startup/runtime failure cannot roll back or stop healthy core services.
- [x] Verify public CI in core-only mode without proprietary SDK binaries while separately validating the HIK Compose profile configuration.

### Phase 5 camera-management UI convergence

- [x] Replace the temporary desktop detail drawer with the persistent camera list/detail split workspace while preserving `?camera_id=<id>` deep links.
- [x] Treat Disabled as its own summary/filter state rather than a connectivity failure.
- [x] Drive camera cards/detail connection identity from canonical `CameraConnection` adapter/host/config state.
- [x] Replace separate manual RTSP / ONVIF / HIK add flows with one reusable adapter-aware `CameraEditorDialog`.
- [x] Drive adapter selection from `GET /api/camera-adapters`, including visible unavailable capabilities and optional draft Probe.
- [x] Preserve Camera ID/history when switching adapters through the unified editor.
- [x] Replace the easy enabled toggle with explicit Disable/Re-enable device-management actions and confirmation semantics.
- [x] Add camera-scoped history summaries/deep links for recordings, activity, blocking system events, health samples, and pending uploads.
- [x] Gate permanent deletion through deletion-impact inspection, blocker deep links, and explicit typed-name confirmation; do not offer cascade deletion.
- [x] Replace detail-workspace Teleports/MutationObserver wiring with an explicit `CameraDetailWorkspace` component.
- [x] Remove the old standalone ONVIF/HIK frontend add components.

### Contract

Only after the new model has run successfully for a stable release window:

- [ ] Remove legacy RTSP connection fields from `Camera`.
- [ ] Remove compatibility shadow writes.
- [ ] Remove legacy adapter-specific persistence paths/routes that are no longer used.
- [x] Remove old standalone ONVIF/HIK frontend add components. This frontend-only cleanup was safely completed during Phase 5 UI convergence; the persistence/API contract removals above remain deferred.

## Migration invariants

The following conditions are mandatory before a deployment is considered successful:

1. Camera row count is unchanged by the migration.
2. Every pre-existing Camera ID is unchanged.
3. Every pre-existing Camera has exactly one `CameraConnection`.
4. Every migrated existing connection is `manual_rtsp`.
5. Recording count and `recordings.camera_id` values are unchanged.
6. Motion-event count and `motion_events.camera_id` values are unchanged.
7. Health-sample count and `camera_health_samples.camera_id` values are unchanged.
8. No recording/media files are deleted or moved by the schema migration.
9. Existing encrypted passwords are copied byte-for-byte; migration does not decrypt credentials.
10. Runtime workers start only after Alembic migration and consistency checks succeed.

## Verification

### Manual RTSP + ONVIF Switch slice

The manual RTSP + ONVIF Switch slice was verified in CI run `#1182` (`35109383963`) and re-verified against the integrated mainline in CI `#1194` (`35116242363`): all four backend pytest shards, backend quality/Ruff, frontend, Docker smoke, database migration compatibility, and the aggregate backend job completed successfully.

The verified behavior includes current-connection precedence over legacy shadows, legacy fallback only when no current connection exists, manual RTSP and ONVIF current-connection writes, ONVIF connection-scoped runtime resolution, credential-free cached ONVIF URIs, stable Camera/connection identity on updates, and rollback-window shadow-field synchronization.

### RuntimeCoordinator lifecycle slice

The production-code head for the RuntimeCoordinator slice was verified in CI `#1204` (`35119089053`). All four backend pytest shards, backend quality/Ruff, HIK bridge tests, frontend, Docker smoke/database migration compatibility, and the aggregate backend job completed successfully.

That verification covers recorder ownership, coordinated stop/reload sequencing, manual-recording restoration, schedule reconciliation, event-buffer/motion restore order, RTSP and ONVIF update routing, Camera deletion teardown, disabled-camera start/restart/preview guards, continued disabled-camera Probe access, and regular-recorder/event-buffer handoff.

The RuntimeCoordinator slice itself intentionally did not claim active preview-session termination or HIK temporary-session lifecycle integration; those are completed by the later active media-session lifecycle slice below. Long-running worker revision invalidation is completed by the subsequent connection revision guard slice below.

### Connection revision guard slice

The production-code head for the connection revision guard slice was verified in CI `#1224` (`35166918738`). All four backend pytest shards, backend quality/Ruff, HIK bridge tests, Docker smoke/database migration compatibility, and the aggregate backend job completed successfully; frontend was correctly skipped because this slice has no frontend changes.

That verification covers captured `CameraConnection.revision` values in recorder and motion runtime configs, tri-state current/stale/unknown revision checks, stale recorder and motion reconnect termination without converting lifecycle staleness into device failures, event pre-roll worker reconnect invalidation, and replacement of an event-buffer worker when the revision changes even if the resolved URI does not. The existing event-buffer handoff regression suite also remained green, preserving active-event capture ownership across normal-recorder transitions.

### HIK canonical connection + adapter switching slice

The production-code head for the HIK canonical connection and adapter switching slice was verified in CI `#1271` (`35189648734`). All four backend pytest shards, backend quality/Ruff, HIK bridge tests, Docker build/start smoke, database migration compatibility, and the aggregate backend job completed successfully; frontend was correctly skipped because this slice has no frontend changes.

That verification covers the Expand-only `hik_connection_configs` migration with no historical HIK backfill, strict HIK current-connection writes, current-first HIK runtime resolution, canonical HIK API persistence with rollback shadows, stable Camera and `CameraConnection` identity across three-way adapter switching, single-step revision increments, stale adapter-config removal, target validation before runtime stop/persistence, rollback plus old-runtime restoration on commit failure, persisted new connection state when post-commit runtime restoration fails, and schedule validation before stopping an existing runtime. HIK media proxy regressions also preserve empty-chunk filtering and best-effort bridge cleanup.

Active preview-session termination and adapter-specific temporary-session release are completed by the active media-session lifecycle slice below. Contract-phase legacy-field/shadow-write/route cleanup remains deferred until the new model has run successfully for a stable release window.

### Active media-session lifecycle slice

The production-code head for the active media-session lifecycle slice was verified in CI `#1290` (`35201540794`). All four backend pytest shards, backend quality/Ruff, HIK bridge tests, Docker build/start smoke, database migration compatibility, and the aggregate backend job completed successfully; frontend was correctly skipped because this slice has no frontend changes.

That verification covers process-local camera-scoped media-session ownership, idempotent detail-preview FFmpeg teardown, independent preview-wall slot teardown without closing unrelated camera slots or the WebSocket, HIK bridge `stream_id` registration and best-effort DELETE cleanup, media-session teardown before motion/event/recorder/schedule runtime teardown, and a preview/media-agnostic `restore()` path. Existing preview fallback behavior, HIK empty-chunk filtering, early-consumer-close cleanup, and adapter target validation before runtime teardown remained covered by regression tests.

### Unified camera adapter API slice

The production-code head for the Phase 3 unified camera adapter API slice was verified in CI `#1326` (`35230026559`). All four backend pytest shards, backend quality/Ruff, HIK bridge compile/tests, Docker build/start smoke, database migration compatibility, and the aggregate backend job completed successfully; frontend was correctly skipped because this slice has no frontend changes.

That verification covers the shared adapter capability registry, discriminated nested connection schemas, credential-safe draft probing, canonical generic create/update/switch transactions, offline/unverified ONVIF/HIK saves, stable Camera and `CameraConnection` identity, single-step revision changes, adapter validation before runtime teardown, rollback/runtime restoration behavior, persisted current-connection Probe without revision mutation, ONVIF rediscovery runtime reload without revision inflation, and ONVIF/HIK legacy routes acting as compatibility wrappers rather than independent persistence implementations.

### Phase 4 optional HIK deployment slice

The implementation head `09d48845735661cf5e1a559fd6ce9375795e4de2` was verified in CI `#1354` (`35257054928`). All four backend pytest shards, backend quality/Ruff and HIK bridge tests, frontend lint/tests/build, aggregate backend verification, and the redesigned core-only Docker smoke completed successfully.

The Docker smoke verified both default and `hik` profile Compose configuration, proved default core startup does not create `hik-bridge`, validated database migration compatibility, confirmed backend remains internal-only, and checked `/api/camera-adapters` reports HIK unavailable with the deployment-disabled reason. The same verification preserved runtime timezone/frontend routes, backend proxying, and upload WebSocket behavior without any proprietary SDK runtime in CI.

The Phase 4 implementation also verifies that deployment-disabled HIK capability does not access the bridge, does not mutate persisted camera connectivity into an offline failure, and remains an optional post-core deployment stage. The status-only closeout commit following this implementation verification must still pass the normal exact-head PR CI before merge.

## Why this is simpler than the generic migration

Because there is no legacy ONVIF/HIK production data to preserve, the migration does not need to reconcile existing `onvif_device_metadata` or `hik_device_metadata` into active connections. ONVIF and HIK can use the new adapter implementations without risking existing camera history, while legacy metadata stays outside the canonical current-connection source of truth.

The migration concern therefore remains narrow: preserve Camera IDs/history, move existing RTSP connection data out of `Camera` safely, keep new manual RTSP/ONVIF/HIK state canonical in the current connection layer, support explicit adapter replacement on the same stable identities, centralize the bounded recorder/schedule/motion/event/media lifecycle, expose one unified adapter contract without inferring historical adapter state, and keep proprietary HIK runtime capability optional at deployment time.
