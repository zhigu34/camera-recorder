# Camera Connection Revision Guard Design

Status: Approved implementation slice

Date: 2026-09-17

## Goal

Long-running camera workers must never keep reconnecting with a stale `CameraConnection` after the current connection changes.

`CameraConnection.revision` is the canonical generation number. A worker records the revision that produced its runtime configuration. Before every new device connection attempt or reconnect attempt, it verifies that the persisted current connection still has the same revision. If not, the worker exits normally and leaves restart/reload responsibility to `CameraRuntimeCoordinator`.

## Scope

This slice covers:

- regular recording `CameraWorker`
- motion detection supervision
- event pre-roll/ring-buffer worker
- shared loading/checking of current connection revision
- regression tests for stale workers and legacy/no-connection compatibility

This slice does not cover:

- adapter switching API/UI
- active preview-session termination
- HIK bridge temporary-session release
- cross-process generation coordination
- replacing `CameraRuntimeCoordinator`

## Runtime contract

### Runtime configuration

Runtime configs produced from a persisted Camera carry `connection_revision: int | None`.

- Cameras with a current `CameraConnection` receive its integer revision.
- Legacy/test configs without a current connection use `None`.
- `None` means "no persisted revision guard available" and preserves current compatibility behavior.

### Revision checker

A small shared service loads the current Camera and current connection by `camera_id` and returns whether a captured revision is still current.

Rules:

1. `expected_revision is None` -> current for compatibility.
2. Camera missing -> stale.
3. Camera disabled -> stale.
4. Expected revision exists but current connection is missing -> stale.
5. Current connection revision differs -> stale.
6. Equal revision -> current.

The checker does not restart anything and does not mutate state.

### Recorder

`CameraWorker` checks revision:

- immediately before each FFmpeg spawn, including the first spawn
- after reconnect backoff and before the next spawn

If stale, it exits its loop as a normal lifecycle stop. It must not:

- spawn FFmpeg with the old URI
- increment failure counters
- emit connection-lost/offline/failure-streak events
- send offline notifications

An already-running FFmpeg process is still primarily stopped by `CameraRuntimeCoordinator.reload()`. The revision guard is the race/failure safety net for later reconnect attempts, not a polling mechanism that kills healthy processes continuously.

### Motion detection

`MotionWorkerConfig` carries the captured revision. `MotionDetectionManager._supervise()` checks it before creating/running each worker attempt and again after reconnect delay before another attempt.

A stale revision ends supervision normally and records a stopped/stale lifecycle state rather than a device error.

### Event pre-roll

`EventBufferWorker` carries the captured revision. Its reconnect loop checks revision before each FFmpeg spawn and after retry delay.

`EventRecordingManager.reconcile_once()` also treats a worker with a different revision as replaceable even if its URI happens to be unchanged.

Active event pre-roll ownership semantics from PR #60 remain unchanged. This slice must not reintroduce the handoff regression.

## Error handling

Revision lookup failure due to a transient database/runtime exception is not treated as confirmed staleness. The worker should log/record the lookup problem using existing local logging behavior and avoid converting it into a device failure. The next normal retry may check again.

Confirmed stale state is a lifecycle condition, not a device connectivity failure.

## Alternatives considered

### Coordinator cancellation only

Rejected as insufficient. `CameraRuntimeCoordinator.reload()` remains the primary transition, but a worker can survive or race cancellation and then reconnect using captured stale credentials/URI.

### In-memory generation token only

Rejected as the canonical guard. It would be lost when managers are recreated and could diverge from persisted `CameraConnection.revision`.

### Database revision guard

Selected. It directly enforces the existing architecture contract and remains valid across manager recreation within the backend process.

## Testing

Use TDD with focused tests that prove:

- runtime configs capture the current connection revision
- recorder exits before spawning/re-spawning when revision is stale
- stale recorder exit does not count as device failure
- motion supervision stops before constructing another worker when stale
- event ring stops reconnecting when stale
- event ring is replaced when revision changes even if URI stays the same
- `None` revision preserves legacy/unit-test behavior
- PR #60 event pre-roll handoff tests remain green

Run the full sharded backend suite, Ruff/HIK checks, and Docker smoke before merge.
