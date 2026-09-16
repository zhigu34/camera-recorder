# Camera Architecture Refactor — Migration Notes

Status: **Switch slice complete for manual RTSP + ONVIF**

Date: 2026-09-16

## Current production data assumption

The current installation only contains cameras configured through the existing manual RTSP path.

Therefore the migration MUST treat existing persisted cameras as RTSP cameras and MUST NOT attempt to infer or manufacture historical ONVIF/HIK connection data.

ONVIF and HIK SDK remain supported target adapters after the refactor, but they are future/current selectable connection methods rather than legacy data that needs backfilling.

## Safe migration strategy

Use an Expand -> Switch -> Contract rollout.

Phase 1 and the manual-RTSP/ONVIF Switch slice completed items are checked below. Unchecked items remain deliberate follow-up work and are not implied by the completed slice.

### Expand

- [x] Create `camera_connections`.
- [x] Create `rtsp_connection_configs`.
- [x] Create an empty ONVIF connection-config table for the new architecture; do not backfill it from legacy rows.
- [ ] Create the HIK connection-config table for the new architecture; do not backfill it from legacy rows.
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
- [ ] Move HIK persistence/runtime reads to `CameraConnection` + an HIK adapter config.
- [x] Keep legacy Camera RTSP/auth fields temporarily as compatibility shadow fields for one rollback window.
- [x] During the rollback window, writes through the connection service mirror compatible RTSP endpoint/auth fields back to legacy Camera columns.
- [x] Existing RTSP cameras continue using the same Camera IDs and history after the switch.
- [x] New manual RTSP and ONVIF cameras are created with exactly one current connection.
- [x] New/updated ONVIF cameras persist connection-scoped profile/capability/credential-free URI caches and no longer write new `OnvifDeviceMetadata` state.
- [ ] New HIK connections are created only in the new connection model.
- [ ] Adapter switching (`manual_rtsp -> onvif/hik_sdk`) updates the same Camera ID.
- [x] The dedicated ONVIF API routes remain temporary wrappers over the current connection service rather than an independent persistence path.
- [ ] Convert dedicated HIK API/persistence paths into wrappers over the current connection service.
- [ ] Introduce `CameraRuntimeCoordinator` lifecycle/revision coordination and stale-worker invalidation.

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

## Switch-slice verification

The manual RTSP + ONVIF Switch slice was verified in CI run `#1182` (`35109383963`): all four backend pytest shards, backend quality/Ruff, frontend, Docker smoke, database migration compatibility, and the aggregate backend job completed successfully.

The verified behavior includes current-connection precedence over legacy shadows, legacy fallback only when no current connection exists, manual RTSP and ONVIF current-connection writes, ONVIF connection-scoped runtime resolution, credential-free cached ONVIF URIs, stable Camera/connection identity on updates, and rollback-window shadow-field synchronization.

## Why this is simpler than the generic migration

Because there is no legacy ONVIF/HIK production data to preserve, the migration does not need to reconcile existing `onvif_device_metadata` or `hik_device_metadata` into active connections. ONVIF can be switched to the new adapter implementation without risking existing camera history, while HIK remains explicit follow-up work.

The migration concern therefore remains narrow: preserve Camera IDs/history, move existing RTSP connection data out of `Camera` safely, and make new manual RTSP/ONVIF state canonical in the current connection layer without inferring historical adapter state.
