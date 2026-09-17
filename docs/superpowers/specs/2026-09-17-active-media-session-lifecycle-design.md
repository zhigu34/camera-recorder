# Active Media Session Lifecycle Design

Date: 2026-09-17
Status: Approved design

## Goal

Make active preview/media sessions first-class per-camera runtime resources so disabling, reloading, deleting, or switching a camera connection immediately terminates every session that still owns the old media path.

The lifecycle boundary is intentionally one-way: configuration/runtime teardown invalidates active preview/media sessions, but `restore()` never recreates them. Users reopen previews explicitly, at which point the new/current camera connection is resolved.

## Current problem

The project currently has three short-lived media/session paths that clean up only when their own consumer exits:

1. Detail MJPEG preview owns an FFmpeg process through `PreviewSession`.
2. Preview-wall slots own FFmpeg processes inside `stream_preview_frames()` tasks.
3. HIK internal media requests own HCNetSDK bridge `stream_id` values and delete them only when the HTTP media iterator finishes.

`CameraRuntimeCoordinator.stop_all()` currently coordinates recorder, schedule, motion detection, and event buffering, but it cannot see or terminate any of those short-lived media sessions. As a result, a camera can be disabled, reloaded, or switched to another adapter while an old preview continues consuming the old RTSP/HIK connection and associated resources.

## Decision

Introduce a single backend `CameraMediaSessionRegistry` as the ownership boundary for all short-lived preview/media sessions.

Every active detail preview, preview-wall slot, and HIK bridge stream registers a camera-scoped close callback. `CameraRuntimeCoordinator.stop_all(camera_id)` calls the registry before tearing down motion/event/recorder/schedule runtime. The registry removes the current camera session set atomically, then closes those sessions best-effort.

This design replaces neither recorder ownership nor adapter-specific media resolution. It adds only a common lifecycle registry for resources that should end immediately when a camera's active runtime is invalidated.

## Alternatives considered

### Separate stop logic per preview type

Each API/service could expose its own `stop_camera(camera_id)` and the coordinator could call all of them.

This is initially simple, but it spreads camera-scoped media ownership across multiple modules and requires the coordinator to know implementation details for FFmpeg preview, preview-wall, and HIK bridge sessions. New session types would continue expanding the coordinator.

### Revision-only invalidation

Active sessions could periodically compare `CameraConnection.revision` and eventually exit when stale.

This preserves loose coupling but does not release resources immediately, requires polling/checkpoints inside long-running stream loops, and does not solve camera disable cleanly. It is appropriate for reconnect workers, not interactive sessions that already have an explicit teardown boundary.

### Unified media-session registry — selected

A registry gives one stable dependency to `CameraRuntimeCoordinator`, keeps adapter/process details behind close callbacks, and supports immediate teardown without requiring session restoration semantics.

## Component boundaries

### `CameraMediaSessionRegistry`

Create `backend/app/services/camera_media_session_registry.py` with one process-local singleton used by API/service runtime code.

Conceptual interface:

```python
SessionCloser = Callable[[], Awaitable[None]]

class CameraMediaSessionRegistry:
    async def register(self, camera_id: int, closer: SessionCloser) -> str: ...
    async def unregister(self, camera_id: int, session_id: str) -> None: ...
    async def stop_camera(self, camera_id: int) -> None: ...
    async def stop_all(self) -> None: ...
```

The implementation maintains:

```text
camera_id -> session_id -> closer
```

`session_id` is unique for the process lifetime. The registry does not persist sessions in SQLite and does not expose them as application domain state.

The registry owns membership only. It never knows whether a closer stops FFmpeg, cancels a task, or deletes a HIK bridge stream.

### Detail MJPEG preview

`PreviewSession` gains an idempotent public `close()` method around existing FFmpeg process teardown.

The camera preview endpoint registers the opened `PreviewSession.close` callback before returning `StreamingResponse`. The response iterator unregisters the session in `finally` after natural client disconnect/end-of-stream.

If `stop_camera(camera_id)` closes the session first, the FFmpeg pipe ends and the HTTP response naturally terminates. The iterator's later unregister/close path remains safe and idempotent.

### Preview wall

The preview-wall service must stop hiding the FFmpeg process inside a bare coroutine whose only lifetime owner is its task.

Introduce a small wall-slot session abstraction that owns the FFmpeg process and exposes:

```python
async def stream(on_frame): ...
async def close(): ...
```

Each slot is registered independently using its `camera_id`. Closing one camera therefore terminates only that camera's slot, not the WebSocket or other slots in the same wall request.

The WebSocket remains connected when one slot is externally stopped. Its slot task completes; other slot tasks continue. Existing per-slot error/status behavior remains unchanged except that an externally invalidated slot ends cleanly instead of continuing on the old connection.

### HIK internal media

Each `/internal/hik-media/{camera_id}/{role}` request registers a closer after `create_stream()` returns a bridge `stream_id`.

The closer calls `HikBridgeClient.stop_stream(stream_id)` with best-effort semantics. The media iterator unregisters the registry entry in `finally` after its own existing best-effort stop.

The registry does not introduce a persistent HIK bridge session database or bridge-wide session inventory. It tracks only sessions created by this backend process and only for lifecycle invalidation.

## Runtime coordinator integration

`CameraRuntimeCoordinator.stop_all(camera_id, ...)` becomes the single camera-lifecycle entrypoint for active short-lived media teardown.

Required order:

```text
1. media_session_registry.stop_camera(camera_id)
2. motion_detection_manager.stop_camera(camera_id)
3. event_recording_manager.end_event(camera_id)
4. event_recording_manager.stop_camera(camera_id)
5. recorder_manager.stop(camera_id) when running
6. detach/forget recording schedule ownership
```

The media session stop comes first so no active preview continues consuming an old connection while the remaining camera runtime is being torn down.

`CameraRuntimeCoordinator.restore()` remains unchanged with respect to preview/media sessions. It restores only recorder/schedule/event-buffer/motion responsibilities already owned by the coordinator.

This means the following operations automatically acquire the new behavior because they already route through `stop_all()`/`reload()`:

- camera disable through update flows
- same-adapter connection reloads
- cross-adapter connection switches
- camera deletion
- any later camera lifecycle operation that reuses the coordinator

Target adapter validation/probing remains before `stop_all()` for switching APIs. Invalid target configuration must not terminate a currently valid preview.

## Concurrency and idempotency

The registry protects membership changes with an async lock.

`stop_camera(camera_id)` performs an atomic detach:

1. acquire registry lock;
2. remove the entire current session map for `camera_id`;
3. release the lock;
4. invoke detached closers outside the lock.

This creates a clear generation boundary. Sessions registered after the detach are not part of that stop operation and are not accidentally closed.

A session that naturally ends concurrently with `stop_camera()` may call `unregister()` after its entry has already been detached. `unregister()` is therefore idempotent and treats missing entries as success.

Every concrete session `close()` must also be idempotent. Double cleanup from client disconnect plus coordinator teardown must not raise or leak registry state.

The registry must never await external/process cleanup while holding its membership lock.

## Error handling

Media-session cleanup is best-effort and must not block camera configuration lifecycle.

For `stop_camera(camera_id)`:

- every detached closer is attempted;
- failure of one closer does not skip remaining closers;
- cleanup failures are logged with camera/session context;
- cleanup exceptions are not propagated to `CameraRuntimeCoordinator.stop_all()`.

For natural session shutdown:

- existing preview FFmpeg cleanup behavior remains;
- HIK `stop_stream()` remains best-effort;
- unregister runs even when stream iteration fails.

This is deliberate: failing to stop one stale preview is observable operationally, but must not leave a camera half-updated or prevent a disable/delete/switch transaction from completing.

## Lifecycle semantics

### Camera disabled

An update that transitions or reloads an enabled camera through the coordinator terminates all current preview/media sessions. `restore()` sees the disabled camera and does not recreate runtime or preview sessions.

### Same-adapter reload

All current preview/media sessions are terminated before the old runtime is stopped. After persistence and runtime restore, users explicitly reopen preview against the updated connection.

### Cross-adapter switch

Target validation occurs first. Once the switch is ready to persist, coordinator teardown terminates all old preview/media sessions before the adapter/config mutation is committed. After successful persistence, runtime restore does not recreate previews.

If database persistence fails, existing recorder/schedule/motion/event runtime may be restored from the snapshot, but invalidated preview/media sessions stay closed. The user can reopen them against the rolled-back connection.

### Camera deletion

All preview/media sessions terminate before recorder/motion/event/schedule teardown and before final deletion proceeds.

## Testing strategy

Implementation must use TDD and preserve existing preview behavior while adding lifecycle ownership.

### Registry tests

Add focused tests proving:

- register/unregister membership;
- `stop_camera()` closes all and only sessions for the target camera;
- atomic detach means a session registered during cleanup survives the current stop;
- missing/double unregister is safe;
- closer exceptions do not stop later closers or propagate;
- `stop_all()` drains every camera;
- registry is empty after natural and forced teardown.

### Detail preview tests

Prove that:

- an opened MJPEG preview registers under the correct `camera_id`;
- coordinator/media-registry stop terminates its FFmpeg process;
- normal client disconnect unregisters the session;
- concurrent disconnect and external stop are idempotent;
- existing auto sub-stream to main-stream fallback remains intact.

### Preview-wall tests

Prove that:

- each slot registers independently by camera;
- stopping camera A ends only A's slot while camera B's slot remains active;
- WebSocket-level disconnect closes/unregisters all remaining slot sessions;
- per-slot fallback/error status remains compatible;
- process teardown is idempotent.

### HIK media tests

Prove that:

- a created HIK bridge `stream_id` registers against the camera before streaming;
- `stop_camera()` deletes the active bridge stream;
- natural HTTP consumer disconnect unregisters and deletes it;
- duplicate cleanup is safe/best-effort;
- stop failures do not propagate into camera lifecycle;
- existing empty-chunk filtering and cleanup semantics remain unchanged.

### Runtime coordinator tests

Extend coordinator tests to prove:

- media-session teardown happens before motion/event/recorder/schedule teardown;
- `restore()` never recreates preview/media sessions;
- disable, reload, deletion, and adapter-switch callers inherit teardown through existing coordinator paths.

## Observability

Keep observability minimal for this slice.

Log cleanup failures and, at debug level if useful, camera/session registration and removal. Do not add a new dashboard, metrics subsystem, or persistent session table.

## Scope boundaries

Included:

- process-local camera media-session registry;
- detail MJPEG active-session termination;
- preview-wall per-slot active-session termination;
- HIK bridge stream termination;
- RuntimeCoordinator integration;
- tests and migration-status documentation updates.

Explicitly out of scope:

- frontend automatic preview reconnect;
- preserving/recreating user preview state after reload;
- HIK bridge global/central session dashboard or persistent registry;
- recorder/schedule/motion/event ownership redesign;
- media transcoding changes;
- adapter persistence changes;
- connection-model schema changes;
- legacy route/column contract cleanup.

## Success criteria

The slice is complete when all of the following hold:

1. No active detail preview, preview-wall slot, or HIK bridge stream can remain intentionally alive across camera disable, reload, deletion, or adapter switch.
2. Stopping one camera never terminates another camera's media sessions.
3. Runtime restore does not recreate preview/media sessions.
4. Invalid switch targets do not terminate existing previews because validation still precedes teardown.
5. Client disconnect and coordinator teardown can race without double-close failures or registry leaks.
6. A cleanup failure cannot block camera configuration persistence or lifecycle teardown.
7. Existing recorder/event/motion/schedule semantics and preview fallback behavior remain green in the full CI suite.
