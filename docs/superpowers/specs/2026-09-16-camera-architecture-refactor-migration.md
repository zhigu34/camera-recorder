# Camera Architecture Refactor — Migration Notes

Status: **Switch slice complete for manual RTSP + ONVIF + HIK; RuntimeCoordinator lifecycle and connection revision guard slices complete**

Date: 2026-09-16

## Current production data assumption

The current installation only contains cameras configured through the existing manual RTSP path.

Therefore the migration MUST treat existing persisted cameras as RTSP cameras and MUST NOT attempt to infer or manufacture historical ONVIF/HIK connection data.

ONVIF and HIK SDK remain supported target adapters after the refactor, but they are future/current selectable connection methods rather than legacy data that needs backfilling.

## Safe migration strategy

Use an Expand -> Switch -> Contract rollout.

Phase 1, the manual-RTSP/ONVIF/HIK Switch slice, the bounded RuntimeCoordinator lifecycle slice, and the connection revision guard slice completed items are checked below. Unchecked items remain deliberate follow-up work and are not implied by the completed slices.

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
- [x] The dedicated ONVIF API routes remain temporary wrappers over the current connection service rather than an independent persistence path.
- [x] Convert dedicated HIK API/persistence paths into wrappers over the current connection service.
- [x] Introduce `CameraRuntimeCoordinator` for recorder/schedule/motion/event-buffer stop/reload orchestration.
- [x] Route manual RTSP connection/policy edits, ONVIF re-discovery updates, and Camera deletion through the runtime coordinator.
- [x] Treat `Camera.enabled=false` as the runtime master switch for manual start, restart, and new preview requests while still allowing explicit one-shot Probe.
- [x] Preserve the event-buffer handoff invariant when manually starting normal recording by using `start_regular_recorder`.
- [ ] Terminate already-active preview sessions when a Camera is disabled or reloaded.
- [ ] Release adapter-specific temporary sessions on disable/reload, especially HIK bridge streams.
- [x] Add current-connection revision stale-worker invalidation inside long-running reconnect loops.

### Contract

Only after the new model has run successfully for a stable release window:

- [ ] Remove legacy RTSP connection fields from `Camera`.
- [ ] Remove compatibility shadow writes.
- [ ] Remove legacy adapter-specific persistence paths/routes that are no longer used.
- [ ] Remove old standalone ONVIF/HIK frontend add components.

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

The RuntimeCoordinator slice intentionally does not claim active preview-session termination or HIK temporary-session lifecycle integration; those remain explicit follow-up items above. Long-running worker revision invalidation is completed by the subsequent connection revision guard slice below.

### Connection revision guard slice

The production-code head for the connection revision guard slice was verified in CI `#1224` (`35166918738`). All four backend pytest shards, backend quality/Ruff, HIK bridge tests, Docker smoke/database migration compatibility, and the aggregate backend job completed successfully; frontend was correctly skipped because this slice has no frontend changes.

That verification covers captured `CameraConnection.revision` values in recorder and motion runtime configs, tri-state current/stale/unknown revision checks, stale recorder and motion reconnect termination without converting lifecycle staleness into device failures, event pre-roll worker reconnect invalidation, and replacement of an event-buffer worker when the revision changes even if the resolved URI does not. The existing event-buffer handoff regression suite also remained green, preserving active-event capture ownership across normal-recorder transitions.

### HIK canonical connection + adapter switching slice

The production-code head for the HIK canonical connection and adapter switching slice was verified in CI `#1271` (`35189648734`). All four backend pytest shards, backend quality/Ruff, HIK bridge tests, Docker build/start smoke, database migration compatibility, and the aggregate backend job completed successfully; frontend was correctly skipped because this slice has no frontend changes.

That verification covers the Expand-only `hik_connection_configs` migration with no historical HIK backfill, strict HIK current-connection writes, current-first HIK runtime resolution, canonical HIK API persistence with rollback shadows, stable Camera and `CameraConnection` identity across three-way adapter switching, single-step revision increments, stale adapter-config removal, target validation before runtime stop/persistence, rollback plus old-runtime restoration on commit failure, persisted new connection state when post-commit runtime restoration fails, and schedule validation before stopping an existing runtime. HIK media proxy regressions also preserve empty-chunk filtering and best-effort bridge cleanup.

Active preview-session termination and adapter-specific temporary-session release remain deliberate follow-up work. Contract-phase legacy-field/shadow-write/route cleanup also remains deferred until the new model has run successfully for a stable release window.

## Why this is simpler than the generic migration

Because there is no legacy ONVIF/HIK production data to preserve, the migration does not need to reconcile existing `onvif_device_metadata` or `hik_device_metadata` into active connections. ONVIF and HIK can use the new adapter implementations without risking existing camera history, while legacy metadata stays outside the canonical current-connection source of truth.

The migration concern therefore remains narrow: preserve Camera IDs/history, move existing RTSP connection data out of `Camera` safely, keep new manual RTSP/ONVIF/HIK state canonical in the current connection layer, support explicit adapter replacement on the same stable identities, and centralize the bounded recorder/schedule/motion/event lifecycle without inferring historical adapter state.
