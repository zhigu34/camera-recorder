# Camera Architecture Refactor — Migration Notes

Status: **Confirmed migration constraint**

Date: 2026-09-16

## Current production data assumption

The current installation only contains cameras configured through the existing manual RTSP path.

Therefore the migration MUST treat existing persisted cameras as RTSP cameras and MUST NOT attempt to infer or manufacture historical ONVIF/HIK connection data.

ONVIF and HIK SDK remain supported target adapters after the refactor, but they are future/current selectable connection methods rather than legacy data that needs backfilling.

## Safe migration strategy

Use an Expand -> Switch -> Contract rollout.

### Expand

- [ ] Create `camera_connections`.
- [ ] Create `rtsp_connection_configs`.
- [ ] Create empty ONVIF/HIK connection-config tables for the new architecture; do not backfill them from legacy rows.
- [ ] For every existing Camera, create exactly one `CameraConnection` with `adapter=manual_rtsp`.
- [ ] Copy existing `Camera.ip` -> `CameraConnection.host`.
- [ ] Copy existing `Camera.username` -> `CameraConnection.username`.
- [ ] Copy existing `Camera.password_encrypted` -> `CameraConnection.password_encrypted` without decrypting/re-encrypting it.
- [ ] Set initial `CameraConnection.revision=1`.
- [ ] Set initial verification state from current persisted connectivity/probe information where it is unambiguous; otherwise use `unverified` rather than guessing.
- [ ] Copy `Camera.rtsp_port`, `Camera.rtsp_path`, and `Camera.sub_rtsp_path` into `RtspConnectionConfig`.
- [ ] Preserve every existing `Camera.id` exactly.
- [ ] Preserve all Recording/Event/Motion/Health references to existing `camera_id` values.
- [ ] Change historical camera foreign keys from destructive cascade behavior to RESTRICT/NO ACTION-safe behavior.
- [ ] Before destructive SQLite table rebuild migrations, create a database backup/snapshot.
- [ ] Add migration verification: every existing Camera must have exactly one current connection after backfill.
- [ ] Add migration verification: every backfilled connection must be `manual_rtsp` for this installation.
- [ ] If migration encounters a legacy Camera whose adapter is unexpectedly not `manual_rtsp`, abort migration with a clear error instead of guessing how to transform it.

### Switch

- [ ] Make `CameraConnection` + adapter config the canonical read/write source.
- [ ] Keep legacy Camera RTSP fields temporarily as compatibility shadow fields for one rollback window.
- [ ] During the rollback window, writes through the new connection service mirror compatible RTSP endpoint/auth fields back to legacy Camera columns.
- [ ] Existing RTSP cameras continue using the same Camera IDs and history after the switch.
- [ ] New ONVIF/HIK connections are created only in the new connection model.
- [ ] Adapter switching (`manual_rtsp -> onvif/hik_sdk`) updates the same Camera ID.
- [ ] Existing dedicated ONVIF/HIK API routes, if temporarily retained, become wrappers over the unified connection service rather than independent persistence paths.

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

## Why this is simpler than the generic migration

Because there is no legacy ONVIF/HIK production data to preserve, the migration does not need to reconcile existing `onvif_device_metadata` or `hik_device_metadata` into active connections. Those models can be replaced/refactored as part of the new adapter implementation without risking existing camera history.

The migration concern is therefore narrow: preserve Camera IDs/history and move the existing RTSP connection data out of `Camera` into the new connection layer safely.
