# ONVIF PullPoint Native Events

Date: 2026-09-18

## Scope

This slice adds the first real `camera.onvif` event source behind the existing Event Detection registry.

It includes:

- ONVIF Events `GetEventProperties`.
- PullPoint subscription creation, PullMessages polling, renewal and unsubscribe.
- Topic/message normalization into the existing DetectionEvent contract.
- Generic `detection_events` persistence for non-legacy providers.
- Per-camera ONVIF native-event enable state, default off.
- Runtime manager with reconnect/error state independent from camera connectivity.
- Mutual exclusion between `camera.onvif` and `local.motion` while both can emit motion events.
- `/api/detection-events` merging legacy MotionEvent rows with generic detection events.
- Camera deletion impact including generic detection-event history.
- Event Detection UI showing and enabling/disabling the ONVIF source.

## Non-goals

- PTZ control.
- Event-driven recording policy or cross-camera trigger rules.
- Migrating legacy `motion_events`.
- Persisting a general multi-provider preference graph.
- Vendor-specific configuration APIs.
- Claiming an event capability from an Events XAddr alone.

## Persistence

`onvif_event_settings`

- `camera_id` PK/FK CASCADE.
- `enabled` boolean, default false.

`detection_events`

- `id` provider-local integer ID.
- `camera_id` FK RESTRICT.
- `source_kind`, `provider`, `event_type`.
- `started_at`, `ended_at`.
- optional `confidence`, `recording_id`.
- JSON metadata with original topic/source/data/property operation.

The public DetectionEvent identity is the pair `(provider, id)`; legacy MotionEvent IDs remain unchanged.

## Capability model

An ONVIF camera is:

- `unsupported` when the current adapter is not ONVIF or it advertises no Events service.
- `unavailable` while its current ONVIF connection is not verified.
- `available` when a verified current ONVIF connection advertises Events.

A successful saved-camera Probe also attempts `GetEventProperties`. Failure to read EventProperties is non-fatal for Device/Media probing; the Events service remains available and unknown vendor topics can still be consumed.

Known topic mapping:

- motion / cell motion -> `motion`
- person / human -> `person`
- vehicle / car -> `vehicle`
- intrusion / line crossing / region -> `intrusion`
- tamper -> `tamper`
- digital input -> `digital_input`
- otherwise -> `unknown`

Unknown topics are persisted with original topic and metadata.

## Runtime

`OnvifEventManager` owns one asyncio task per enabled camera:

1. Load current verified ONVIF connection and revision.
2. Create PullPointSubscription.
3. Poll PullMessages with bounded timeout/message limit.
4. Persist normalized notifications.
5. Renew before termination.
6. Reconnect with bounded backoff on protocol/network failure.
7. Unsubscribe best-effort on stop/reconfigure.

The manager state is independent from camera connectivity state.

## Source conflict rule

Until a general per-capability preferred-source model is introduced, enabling `camera.onvif` requires `local.motion` to be disabled, and enabling `local.motion` requires `camera.onvif` to be disabled. This prevents duplicate motion events by default.

## Migration safety

Alembic revision `20260918_0027` only creates new tables. It does not rebuild `cameras`, `motion_events`, or current connection tables.
