# HIK Canonical Connection + Adapter Switching Design

## Goal

Move Hikvision persistence and runtime resolution onto the canonical `CameraConnection` model, then support explicit backend switching among `manual_rtsp`, `onvif`, and `hik_sdk` while preserving the same camera identity and history.

## Scope

This slice includes backend model/migration, HIK create/update persistence, current-first HIK runtime resolution, explicit three-way adapter switch services, and runtime stop/restore orchestration around a switch.

This slice does **not** add a unified frontend connection-type switch UI, terminate already-active preview HTTP sessions, centralize HIK bridge session ownership, remove legacy shadow fields, or delete legacy adapter routes/models.

## Data Model

Add `hik_connection_configs` as a one-to-one adapter config keyed by `camera_connections.id`:

- `connection_id` primary key / FK -> `camera_connections.id`, cascade delete
- `sdk_port`
- `channel`
- `main_stream_type`
- `sub_stream_type`
- `device_serial`
- `device_model`
- `device_name`
- timestamps

`CameraConnection.hik_config` becomes the canonical HIK adapter configuration. `HikDeviceMetadata` remains temporarily as a rollback shadow.

The migration is Expand-only: create the table and relationship, but do not infer or backfill historical `hik_device_metadata` rows into current connections. Existing legacy HIK rows may be read only when a camera has no `CameraConnection` at all.

## HIK Write Path

`upsert_hik_connection()` mirrors the existing strict RTSP/ONVIF upserts:

- no current connection: create `CameraConnection(adapter="hik_sdk", revision=1)` plus `HikConnectionConfig`;
- current adapter `hik_sdk`: update canonical fields and increment `revision` only when connection/config changes;
- current adapter differs: raise `ConnectionAdapterMismatch`;
- continue writing legacy `Camera` connection fields and `HikDeviceMetadata` as rollback shadows.

New HIK cameras must always create the canonical connection. Updating an old legacy HIK camera with no current connection upgrades it into the canonical model.

## Runtime Resolution

HIK runtime resolution is current-connection-first:

1. If `camera.connection` exists, it is authoritative.
2. Its adapter must be `hik_sdk`.
3. Its `hik_config` must exist; if missing, raise a configuration-corruption error and do not fall back.
4. Resolve host, credentials, port, channel and stream type from `CameraConnection + HikConnectionConfig`.
5. Only if `camera.connection is None` may the legacy `Camera + HikDeviceMetadata` compatibility path be used.

The HIK media adapter follows the same rule so newly canonical HIK cameras do not require legacy metadata for runtime correctness.

## Explicit Adapter Switching

Ordinary adapter upserts remain strict and must continue rejecting mismatches. Cross-adapter changes use explicit switch functions.

A switch:

- preserves `camera.id`;
- preserves the existing `camera.connection.id` when one exists;
- increments `CameraConnection.revision` exactly once;
- removes old adapter config rows and creates/updates only the target adapter config;
- updates rollback shadow fields for the target adapter;
- does not rewrite historical Recording/Event/Motion/Health rows.

Target validation/probing happens before switch persistence at the API boundary.

## Runtime Transaction Semantics

Switch orchestration uses `RuntimeCoordinator` in two phases:

1. Stop managed runtime and capture the previous runtime ownership snapshot.
2. Persist the new adapter configuration in one database transaction.
3. Restore runtime from the captured snapshot using the newly persisted connection.

If persistence fails, roll back and restore runtime against the unchanged old connection. If persistence succeeds but runtime restoration fails, keep the new persisted connection and surface the runtime failure; do not silently roll back the connection.

`RuntimeCoordinator.reload()` is refactored to reuse a separate `restore(camera_id, snapshot, ...)` method so switching does not double-stop and lose the pre-switch ownership snapshot.

## API Integration

Existing dedicated adapter endpoints remain wrappers:

- manual RTSP update endpoint targets `manual_rtsp`;
- ONVIF update endpoint targets `onvif`;
- HIK update endpoint targets `hik_sdk`.

When the current adapter already matches, they use the strict same-adapter upsert. When it differs, they explicitly call the target switch path after successful target validation. No generic frontend switch UI is included yet.

## Verification

TDD coverage must prove:

- migration creates `hik_connection_configs` without backfilling legacy HIK metadata;
- canonical HIK create/update persistence and revision semantics;
- current-first HIK runtime resolution and corruption behavior;
- legacy fallback only when no current connection exists;
- manual RTSP / ONVIF / HIK switching preserves camera ID and connection ID;
- switching increments revision and removes stale adapter config;
- failed target validation leaves the old connection untouched;
- persistence failure restores old runtime/config state;
- successful persistence followed by runtime restart failure does not revert the new connection;
- pre-existing camera history remains attached to the same camera ID.
