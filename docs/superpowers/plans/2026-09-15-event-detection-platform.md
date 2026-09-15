# Event Detection Platform V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-class Event Detection workspace that keeps the existing local motion detector working while introducing stable Device Adapter, Stream Resolver, Event Source Registry, normalized DetectionEvent, and ONVIF-native-event extension boundaries.

**Architecture:** Keep the existing `motion_*` persistence/runtime as the first concrete provider, wrap it behind a generic event-source adapter, and expose aggregate APIs under `/api/cameras/{id}/event-detection`. Persist `connection_type` and route recording, preview, and local motion through a purpose-based stream resolver. Add a standalone `/event-detection` workspace; camera details retain only a compact detection summary/deep-link card.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, asyncio, FFmpeg, Vue 3, TypeScript, Pinia, Vue Router, Element Plus, Vitest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-15-event-detection-platform-design.md`

## Global Constraints

- V1 implements only `manual_rtsp` devices and the real `local.motion` event source.
- `onvif`, `local.ai`, person, vehicle, intrusion, loitering, and other future capabilities must not be presented as working features.
- Do not rename or migrate `motion_detection_settings`, `motion_zones`, or `motion_events`.
- Preserve existing `/api/cameras/{id}/motion-detection`, motion-zone APIs, `/api/motion-events`, playback timeline behavior, and stored data.
- Persist `connection_type`; existing cameras migrate to `manual_rtsp`.
- Normal camera creation must reject `connection_type="onvif"` until ONVIF protocol support exists.
- Recording, preview, and local motion detection must all use the Stream Resolver boundary.
- Zone create/update/toggle/delete remains immediate; ordinary detector parameters use draft + explicit save.
- Event Center remains the event-consumption UI; Event Detection is configuration.
- Unknown/unregistered source detail/update endpoints return HTTP `404`.
- Final handoff requires backend compileall/full pytest, frontend lint/full tests/build, and Docker smoke green.

---

## File Structure

### Backend create

- `backend/migrations/versions/20260915_0017_camera_connection_type.py`
- `backend/app/services/device_adapter.py`
- `backend/app/services/stream_resolver.py`
- `backend/app/schemas/event_detection.py`
- `backend/app/services/event_detection/registry.py`
- `backend/app/services/event_detection/motion_source.py`
- `backend/app/services/event_detection/__init__.py`
- `backend/app/api/event_detection.py`
- `backend/tests/test_camera_connection_type.py`
- `backend/tests/test_stream_resolver.py`
- `backend/tests/test_event_detection_registry.py`
- `backend/tests/test_event_detection_api.py`

### Backend modify

- `backend/app/models/camera.py`
- `backend/app/schemas/camera.py`
- `backend/app/api/cameras.py`
- `backend/app/api/motion_detection.py`
- `backend/app/services/camera_config.py`
- `backend/app/services/ffmpeg_builder.py`
- `backend/app/services/camera_preview.py`
- `backend/app/services/motion_manager.py`
- `backend/app/api/__init__.py`
- `backend/app/main.py`
- `backend/tests/test_camera_batch.py`
- `backend/tests/test_camera_preview.py`
- `backend/tests/test_ffmpeg_builder.py`
- `backend/tests/test_motion_detection.py`
- `backend/tests/test_motion_manager.py`
- `backend/tests/test_motion_worker.py`

### Frontend create

- `frontend/src/EventDetectionView.vue`
- `frontend/src/event-detection/types.ts`
- `frontend/src/event-detection/state.ts`
- `frontend/src/eventDetectionPlatform.test.ts`
- `frontend/src/eventDetectionState.test.ts`
- `frontend/src/styles/event-detection.css`

### Frontend modify

- `frontend/src/router.ts`
- `frontend/src/WorkspaceRoute.vue`
- `frontend/src/Root.vue`
- `frontend/src/navigation.ts`
- `frontend/src/navigation.test.ts`
- `frontend/src/CamerasWorkspace.vue`
- `frontend/src/cameraMotionPortal.test.ts`
- `frontend/src/main.ts`

---

### Task 1: Persist Camera Connection Type Without Enabling Fake ONVIF

**Files:**
- Create: `backend/migrations/versions/20260915_0017_camera_connection_type.py`
- Create: `backend/tests/test_camera_connection_type.py`
- Modify: `backend/app/models/camera.py`
- Modify: `backend/app/schemas/camera.py`
- Modify: `backend/tests/test_camera_batch.py`

**Interfaces:**
- Produces `Camera.connection_type: str`.
- Produces `CameraConnectionType = Literal["manual_rtsp", "onvif"]`.
- `CameraRead` exposes `connection_type`.
- `CameraCreate` defaults to `manual_rtsp` and rejects `onvif`.
- `CameraUpdate` must not permit changing an existing camera to `onvif` in V1.
- Task 2 consumes `camera.connection_type`.

- [ ] **Step 1: Write failing schema/API tests**

```python
# backend/tests/test_camera_connection_type.py
import pytest
from pydantic import ValidationError

from app.schemas.camera import CameraCreate


def camera_payload(**overrides):
    payload = {
        "name": "gate",
        "ip": "10.0.0.10",
        "username": "admin",
        "password": "secret",
        "rtsp_path": "/main",
    }
    payload.update(overrides)
    return payload


def test_camera_create_defaults_to_manual_rtsp():
    value = CameraCreate(**camera_payload())
    assert value.connection_type == "manual_rtsp"


def test_camera_create_rejects_unimplemented_onvif():
    with pytest.raises(ValidationError):
        CameraCreate(**camera_payload(connection_type="onvif"))
```

Add an existing camera-list/client fixture assertion:

```python
assert response.json()[0]["connection_type"] == "manual_rtsp"
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
cd backend
uv run pytest tests/test_camera_connection_type.py tests/test_camera_batch.py -q
```

Expected: failure because `connection_type` is not defined.

- [ ] **Step 3: Add model/schema field and migration**

```python
# backend/app/models/camera.py
connection_type: Mapped[str] = mapped_column(
    String(32),
    default="manual_rtsp",
    server_default="manual_rtsp",
    nullable=False,
)
```

```python
# backend/app/schemas/camera.py
CameraConnectionType = Literal["manual_rtsp", "onvif"]

class CameraBase(BaseModel):
    connection_type: CameraConnectionType = "manual_rtsp"

class CameraCreate(CameraBase):
    password: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def reject_unimplemented_connection_type(self):
        if self.connection_type != "manual_rtsp":
            raise ValueError("ONVIF camera creation is not available yet")
        return self
```

Do not put the rejection validator on `CameraRead`; reads must remain capable of representing a future `onvif` row. `CameraUpdate` either omits `connection_type` or validates that any supplied value is `manual_rtsp`.

Migration must use exact chain:

```python
revision: str = "20260915_0017"
down_revision: str | None = "20260915_0016"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("cameras")}
    if "connection_type" not in columns:
        op.add_column(
            "cameras",
            sa.Column(
                "connection_type",
                sa.String(length=32),
                nullable=False,
                server_default="manual_rtsp",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("cameras")}
    if "connection_type" in columns:
        with op.batch_alter_table("cameras") as batch_op:
            batch_op.drop_column("connection_type")
```

- [ ] **Step 4: Run focused tests and migration**

```bash
cd backend
uv run pytest tests/test_camera_connection_type.py tests/test_camera_batch.py -q
uv run alembic upgrade head
uv run alembic current
```

Expected: tests pass; Alembic current reports `20260915_0017`; historical rows read `manual_rtsp`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/camera.py backend/app/schemas/camera.py backend/migrations/versions/20260915_0017_camera_connection_type.py backend/tests/test_camera_connection_type.py backend/tests/test_camera_batch.py
git commit -m "feat: add camera connection type"
```

---

### Task 2: Add Device Adapter + Stream Resolver and Migrate Recording, Preview, Motion

**Files:**
- Create: `backend/app/services/device_adapter.py`
- Create: `backend/app/services/stream_resolver.py`
- Create: `backend/tests/test_stream_resolver.py`
- Modify: `backend/app/services/camera_config.py`
- Modify: `backend/app/services/ffmpeg_builder.py`
- Modify: `backend/app/services/camera_preview.py`
- Modify: `backend/app/api/cameras.py`
- Modify: `backend/app/services/motion_manager.py`
- Modify: `backend/tests/test_camera_preview.py`
- Modify: `backend/tests/test_ffmpeg_builder.py`
- Modify: `backend/tests/test_motion_detection.py`
- Modify: `backend/tests/test_motion_manager.py`
- Modify: `backend/tests/test_motion_worker.py`

**Interfaces:**
- Produces `StreamPurpose = Literal["recording", "preview", "detection"]`.
- Produces `StreamRole = Literal["main", "sub"]`.
- Produces immutable `ResolvedStream(uri: str, role: StreamRole, purpose: StreamPurpose)`.
- Produces `resolve_stream(camera: Camera, purpose: StreamPurpose, *, preferred: Literal["auto", "main", "sub"] = "auto") -> ResolvedStream`.
- `manual_rtsp` adapter is the only registered Device Adapter in V1.
- Any camera whose `connection_type != "manual_rtsp"` raises `UnsupportedDeviceAdapter`.

- [ ] **Step 1: Write failing resolver tests**

```python
from app.services.stream_resolver import UnsupportedDeviceAdapter, resolve_stream


def test_recording_uses_main(camera):
    camera.connection_type = "manual_rtsp"
    camera.rtsp_path = "/ch1/main"
    camera.sub_rtsp_path = "/ch1/sub"
    value = resolve_stream(camera, "recording")
    assert value.role == "main"
    assert value.uri.endswith("/ch1/main")


def test_detection_prefers_sub(camera):
    camera.connection_type = "manual_rtsp"
    camera.rtsp_path = "/ch1/main"
    camera.sub_rtsp_path = "/ch1/sub"
    value = resolve_stream(camera, "detection")
    assert value.role == "sub"
    assert value.uri.endswith("/ch1/sub")


def test_detection_falls_back_to_main(camera):
    camera.connection_type = "manual_rtsp"
    camera.rtsp_path = "/stream"
    camera.sub_rtsp_path = None
    value = resolve_stream(camera, "detection")
    assert value.role == "main"


def test_unimplemented_onvif_never_falls_back_to_manual(camera):
    camera.connection_type = "onvif"
    with pytest.raises(UnsupportedDeviceAdapter):
        resolve_stream(camera, "preview")
```

Also test `preferred="main"`, `preferred="sub"`, and `preferred="auto"` preview behavior, preserving the existing substream inference rule.

- [ ] **Step 2: Verify RED**

```bash
cd backend
uv run pytest tests/test_stream_resolver.py -q
```

Expected: import/function failures.

- [ ] **Step 3: Implement protocol-neutral structures and manual adapter**

```python
# backend/app/services/device_adapter.py
from dataclasses import dataclass
from typing import Literal, Protocol

StreamRole = Literal["main", "sub"]
StreamPurpose = Literal["recording", "preview", "detection"]
StreamPreference = Literal["auto", "main", "sub"]

@dataclass(slots=True, frozen=True)
class ResolvedStream:
    uri: str
    role: StreamRole
    purpose: StreamPurpose

class DeviceAdapter(Protocol):
    def resolve_stream(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> ResolvedStream: ...
```

`ManualRtspDeviceAdapter` owns credential decryption, `build_rtsp_url()`, configured substream selection, and the existing `/main -> /sub` inference. It must not expose credentials outside the resulting URI.

- [ ] **Step 4: Implement central dispatch**

```python
# backend/app/services/stream_resolver.py
class UnsupportedDeviceAdapter(RuntimeError):
    pass

_manual_rtsp = ManualRtspDeviceAdapter()


def resolve_stream(camera, purpose, *, preferred="auto"):
    if camera.connection_type == "manual_rtsp":
        return _manual_rtsp.resolve_stream(camera, purpose, preferred=preferred)
    raise UnsupportedDeviceAdapter(
        f"connection type {camera.connection_type} is not implemented"
    )
```

Policy is exact:
- `recording`: main only.
- `preview`: explicit `main/sub` honored; `auto` prefers sub, then inferred sub, then main.
- `detection`: sub, then inferred sub, then main.

- [ ] **Step 5: Migrate preview**

In `backend/app/api/cameras.py`:

```python
resolved = resolve_stream(camera, "preview", preferred=stream)
session = await open_mjpeg_preview(
    stream_uri=resolved.uri,
    rtsp_timeout_us=runtime.rtsp_timeout_us,
    fps=fps,
    width=width,
)
```

Change `backend/app/services/camera_preview.py` so `build_preview_command()` and `open_mjpeg_preview()` consume `stream_uri`. Remove `resolve_preview_path()` only after all callers move to `resolve_stream`; keep FFmpeg process, timeout, and MJPEG streaming responsibilities unchanged.

- [ ] **Step 6: Migrate recorder**

Change `CameraRuntimeConfig`:

```python
@dataclass(slots=True)
class CameraRuntimeConfig:
    id: int
    name: str
    stream_uri: str
    timestamp_mode: str
    fps_num: int | None
    fps_den: int | None
    audio_codec: str | None
    sample_rate: int | None
    audio_frame_samples: int | None
    align_segments_to_clock: bool | None = None
```

`camera_config.runtime_config()` resolves `purpose="recording"`; `ffmpeg_builder.build_record_command()` uses `camera.stream_uri` directly as `-i` and no longer calls `build_rtsp_url()`.

- [ ] **Step 7: Migrate local motion detector**

In `backend/app/services/motion_manager.py`, replace its main/sub path choice with:

```python
resolved = resolve_stream(camera, "detection")
```

Pass `resolved.uri` to the worker/session input and preserve existing runtime reporting by storing `resolved.role` as `runtime.stream`.

- [ ] **Step 8: Run exact stream-consumer regression set**

```bash
cd backend
uv run pytest \
  tests/test_stream_resolver.py \
  tests/test_camera_preview.py \
  tests/test_ffmpeg_builder.py \
  tests/test_motion_detection.py \
  tests/test_motion_manager.py \
  tests/test_motion_worker.py -q
```

Expected: all pass with unchanged external recording/preview/motion behavior.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/device_adapter.py backend/app/services/stream_resolver.py backend/app/services/camera_config.py backend/app/services/ffmpeg_builder.py backend/app/services/camera_preview.py backend/app/api/cameras.py backend/app/services/motion_manager.py backend/tests/test_stream_resolver.py backend/tests/test_camera_preview.py backend/tests/test_ffmpeg_builder.py backend/tests/test_motion_detection.py backend/tests/test_motion_manager.py backend/tests/test_motion_worker.py
git commit -m "refactor: resolve camera streams by purpose"
```

---

### Task 3: Add Generic Event Source Contracts and Bridge `local.motion`

**Files:**
- Create: `backend/app/schemas/event_detection.py`
- Create: `backend/app/services/event_detection/registry.py`
- Create: `backend/app/services/event_detection/motion_source.py`
- Create: `backend/app/services/event_detection/__init__.py`
- Create: `backend/tests/test_event_detection_registry.py`
- Modify: `backend/app/api/motion_detection.py`
- Modify: `backend/tests/test_motion_detection.py`

**Interfaces:**
- Produces `EventSourceDescriptor`, `EventSourceRead`, `DetectionCapabilitySlot`, `EventDetectionOverview`, `DetectionEventRead`.
- Produces `EventSourceAdapter` protocol.
- Produces registry with `register(adapter)`, `get(source_id)`, `ids()`.
- Registers exactly one writable provider: `local.motion`.

- [ ] **Step 1: Write failing registry tests**

```python
def test_default_registry_contains_only_local_motion():
    from app.services.event_detection import event_source_registry
    assert event_source_registry.ids() == ["local.motion"]


@pytest.mark.asyncio
async def test_motion_descriptor_is_local_motion_only(camera, db_session):
    from app.services.event_detection import event_source_registry
    adapter = event_source_registry.get("local.motion")
    descriptor = await adapter.descriptor(camera, db_session)
    assert descriptor.id == "local.motion"
    assert descriptor.source_kind == "local"
    assert descriptor.provider == "motion"
    assert descriptor.capabilities == ["motion"]
    assert descriptor.configurable is True
```

Add duplicate-registration and unknown-ID tests; unknown registry lookup raises `UnknownEventSource`.

- [ ] **Step 2: Verify RED**

```bash
cd backend
uv run pytest tests/test_event_detection_registry.py -q
```

- [ ] **Step 3: Define strict DTOs**

```python
EventSourceKind = Literal["local", "camera_native"]
EventSourceStatus = Literal["available", "unavailable", "unsupported", "error"]
DetectionEventType = Literal[
    "motion", "person", "vehicle", "intrusion", "tamper", "digital_input", "unknown"
]

class EventSourceDescriptor(BaseModel):
    id: str
    provider: str
    source_kind: EventSourceKind
    status: EventSourceStatus
    display_name: str
    capabilities: list[str]
    configurable: bool
    runtime_state: str | None = None
    reason: str | None = None

class EventSourceRead(BaseModel):
    descriptor: EventSourceDescriptor
    config: dict[str, object]
    zones: list[MotionZoneRead] = Field(default_factory=list)
```

`DetectionEventRead` contains exact spec fields: `id`, `camera_id`, `source_kind`, `provider`, `event_type`, `started_at`, `ended_at`, optional `confidence`, `zone_id`, `zone_name`, `recording_id`, `snapshot_url`, and `metadata`.

- [ ] **Step 4: Implement registry**

```python
class UnknownEventSource(KeyError):
    pass

class EventSourceRegistry:
    def __init__(self):
        self._sources: dict[str, EventSourceAdapter] = {}

    def register(self, adapter: EventSourceAdapter) -> None:
        if adapter.source_id in self._sources:
            raise ValueError(f"duplicate event source: {adapter.source_id}")
        self._sources[adapter.source_id] = adapter

    def get(self, source_id: str) -> EventSourceAdapter:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise UnknownEventSource(source_id) from exc

    def ids(self) -> list[str]:
        return list(self._sources)
```

Default `event_source_registry` registers only `LocalMotionEventSource()`.

- [ ] **Step 5: Extract shared legacy motion service operations**

Move the existing read/update persistence logic out of route-only helpers into reusable functions within `motion_source.py` or a small shared service imported by both the legacy router and adapter:

```python
async def read_motion_detection(camera_id: int, db: AsyncSession) -> MotionDetectionRead: ...
async def update_motion_detection(
    camera_id: int,
    payload: MotionDetectionUpdate,
    db: AsyncSession,
) -> MotionDetectionRead: ...
```

The legacy `/motion-detection` endpoints and `LocalMotionEventSource` must call these same functions. Restart behavior remains exactly once per update.

- [ ] **Step 6: Implement `LocalMotionEventSource` bridge**

Its config mapping is exact:

```python
{
    "enabled": value.enabled,
    "sensitivity": value.sensitivity,
    "analysis_fps": value.analysis_fps,
    "analysis_width": value.analysis_width,
    "min_duration_ms": value.min_duration_ms,
    "merge_gap_ms": value.merge_gap_ms,
    "event_min_interval_ms": value.event_min_interval_ms,
}
```

`update()` validates incoming dict through `MotionDetectionUpdate.model_validate(payload)` before delegating to shared legacy update logic.

- [ ] **Step 7: Run registry + legacy motion tests**

```bash
cd backend
uv run pytest tests/test_event_detection_registry.py tests/test_motion_detection.py tests/test_motion_api.py -q
```

Expected: generic registry passes and legacy API behavior remains green.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/event_detection.py backend/app/services/event_detection backend/app/api/motion_detection.py backend/tests/test_event_detection_registry.py backend/tests/test_motion_detection.py backend/tests/test_motion_api.py
git commit -m "feat: add event source registry"
```

---

### Task 4: Expose Aggregate Event Detection APIs and Normalized Events

**Files:**
- Create: `backend/app/api/event_detection.py`
- Create: `backend/tests/test_event_detection_api.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/event_detection.py`

**Interfaces:**
- `GET /api/cameras/{id}/event-detection`
- `GET /api/cameras/{id}/event-detection/sources/{source_id}`
- `PUT /api/cameras/{id}/event-detection/sources/{source_id}`
- `GET /api/detection-events?start=&end=&camera_id=&event_type=&provider=`
- Unknown/unregistered source ID detail/update returns `404` with `detail="event source not found"`.
- Future capabilities are represented only as overview capability slots in V1; `camera.onvif` and `local.ai` are not registered writable sources.

- [ ] **Step 1: Write failing API tests**

```python
def test_event_detection_overview(client, camera_id):
    response = client.get(f"/api/cameras/{camera_id}/event-detection")
    assert response.status_code == 200
    body = response.json()
    assert body["camera"]["id"] == camera_id
    assert any(item["id"] == "local.motion" for item in body["sources"])
    assert any(
        item["event_type"] == "person" and item["status"] == "unavailable"
        for item in body["capability_slots"]
    )


def test_unknown_source_is_404(client, camera_id):
    response = client.get(
        f"/api/cameras/{camera_id}/event-detection/sources/camera.onvif"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "event source not found"
```

Add PUT `local.motion` test and normalized motion event query test.

- [ ] **Step 2: Verify RED**

```bash
cd backend
uv run pytest tests/test_event_detection_api.py -q
```

- [ ] **Step 3: Implement overview**

Overview includes exact honest slots:

```python
[
    DetectionCapabilitySlot(event_type="motion", status="available", source_id="local.motion"),
    DetectionCapabilitySlot(event_type="person", status="unavailable", reason="未安装 AI Provider"),
    DetectionCapabilitySlot(event_type="vehicle", status="unavailable", reason="未安装 AI Provider"),
    DetectionCapabilitySlot(event_type="intrusion", status="unavailable", reason="尚无可用 Provider"),
]
```

`enabled_source_ids` contains `local.motion` only when its current legacy motion config is enabled.

- [ ] **Step 4: Implement source GET/PUT with fixed 404 contract**

```python
try:
    adapter = event_source_registry.get(source_id)
except UnknownEventSource:
    raise HTTPException(status_code=404, detail="event source not found")
```

Then delegate `read()` or `update()`.

- [ ] **Step 5: Implement normalized detection-event query**

For each legacy `MotionEvent`:

```python
DetectionEventRead(
    id=event.id,
    camera_id=event.camera_id,
    source_kind="local",
    provider="motion",
    event_type="motion",
    started_at=event.started_at,
    ended_at=event.ended_at,
    confidence=event.peak_score,
    zone_id=event.zone_id,
    recording_id=event.recording_id,
    snapshot_url=(
        f"/api/motion-events/{event.id}/snapshot" if event.snapshot_path else None
    ),
    metadata=parse_legacy_metadata(event.metadata_json),
)
```

`provider != motion` or `event_type != motion` returns an empty list in V1. Never relabel motion as an intelligent event.

- [ ] **Step 6: Run API/event regression tests**

```bash
cd backend
uv run pytest \
  tests/test_event_detection_api.py \
  tests/test_motion_detection.py \
  tests/test_motion_api.py \
  tests/test_event_motion_websocket.py \
  tests/test_event_timezone.py -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/event_detection.py backend/app/api/__init__.py backend/app/main.py backend/app/schemas/event_detection.py backend/tests/test_event_detection_api.py
git commit -m "feat: expose event detection api"
```

---

### Task 5: Add Frontend Route, Navigation, Types, and Pure Draft State

**Files:**
- Create: `frontend/src/event-detection/types.ts`
- Create: `frontend/src/event-detection/state.ts`
- Create: `frontend/src/eventDetectionState.test.ts`
- Create: `frontend/src/eventDetectionPlatform.test.ts`
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/WorkspaceRoute.vue`
- Modify: `frontend/src/Root.vue`
- Modify: `frontend/src/navigation.ts`
- Modify: `frontend/src/navigation.test.ts`

**Interfaces:**
- Route `/event-detection`, `meta.navKey = "detection"`.
- Root nav label `事件检测`, target `/event-detection`, icon `Aim` from `@element-plus/icons-vue`.
- Produces `eventDetectionRoute(cameraId?: number | null)`.
- Produces pure helpers `cameraIdFromDetectionQuery`, `motionDraftFromSource`, `countMotionDraftChanges`, `serializeMotionSourcePayload`.

- [ ] **Step 1: Write failing route/state tests**

```ts
it('builds event detection deep link', () => {
  expect(eventDetectionRoute(12)).toEqual({
    path: '/event-detection',
    query: { camera_id: '12' },
  })
})

it('normalizes camera query ids', () => {
  expect(cameraIdFromDetectionQuery('12')).toBe(12)
  expect(cameraIdFromDetectionQuery('x')).toBeNull()
})

it('counts one changed motion field', () => {
  expect(countMotionDraftChanges(saved, { ...saved, sensitivity: 'high' })).toBe(1)
})
```

`eventDetectionPlatform.test.ts` also reads source files and asserts `Root.vue`, `router.ts`, and `WorkspaceRoute.vue` contain the new nav key/path/component while `/events` remains present.

- [ ] **Step 2: Verify RED**

```bash
cd frontend
npm test -- eventDetectionState.test.ts eventDetectionPlatform.test.ts navigation.test.ts
```

- [ ] **Step 3: Define DTOs and pure helpers**

```ts
export interface EventSourceDescriptor {
  id: string
  provider: string
  source_kind: 'local' | 'camera_native'
  status: 'available' | 'unavailable' | 'unsupported' | 'error'
  display_name: string
  capabilities: string[]
  configurable: boolean
  runtime_state?: string | null
  reason?: string | null
}
```

`MotionSourceDraft` contains exactly: `enabled`, `sensitivity`, `analysis_fps`, `analysis_width`, `min_duration_ms`, `merge_gap_ms`, `event_min_interval_ms`.

- [ ] **Step 4: Add route and shell navigation**

```ts
// router.ts
{ path: '/event-detection', name: 'event-detection', component: WorkspaceRoute, meta: { navKey: 'detection' } },
```

```ts
// Root.vue
import { Aim, /* existing icons */ } from '@element-plus/icons-vue'

{ key: 'detection', label: '事件检测', description: '移动检测与智能事件来源', target: '/event-detection', group: 'core', icon: markRaw(Aim) },
```

`WorkspaceRoute.vue` lazy-loads `EventDetectionView` and renders it when `renderKey === 'detection'`.

- [ ] **Step 5: Add deep-link helper**

```ts
export function eventDetectionRoute(cameraId?: number | null): RouteLocationRaw {
  if (!cameraId) return { path: '/event-detection' }
  return { path: '/event-detection', query: { camera_id: String(cameraId) } }
}
```

- [ ] **Step 6: Run focused tests**

```bash
cd frontend
npm test -- eventDetectionState.test.ts eventDetectionPlatform.test.ts navigation.test.ts
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/event-detection frontend/src/eventDetectionState.test.ts frontend/src/eventDetectionPlatform.test.ts frontend/src/router.ts frontend/src/WorkspaceRoute.vue frontend/src/Root.vue frontend/src/navigation.ts frontend/src/navigation.test.ts
git commit -m "feat: add event detection navigation"
```

---

### Task 6: Build the Approved Event Detection Workspace

**Files:**
- Create: `frontend/src/EventDetectionView.vue`
- Create: `frontend/src/styles/event-detection.css`
- Modify: `frontend/src/main.ts`
- Reuse: `frontend/src/MotionZoneEditor.vue`
- Test: `frontend/src/eventDetectionPlatform.test.ts`
- Test: `frontend/src/eventDetectionState.test.ts`

**Interfaces:**
- Consumes `/api/cameras`.
- Consumes `/api/cameras/{id}/event-detection`.
- Consumes `/api/cameras/{id}/event-detection/sources/local.motion`.
- Reuses existing motion-zone CRUD endpoints.
- Uses `/api/cameras/{id}/preview.mjpeg?stream=auto` only for selected-camera preview.
- Query `camera_id` is durable selected-camera state.

- [ ] **Step 1: Extend RED UI contract tests**

```ts
expect(viewSource).toContain('事件检测')
expect(viewSource).toContain('检测摄像头')
expect(viewSource).toContain('检测区域')
expect(viewSource).toContain('移动检测')
expect(viewSource).toContain('未安装 AI Provider')
expect(viewSource).toContain('保存设置')
expect(viewSource).toContain('重置')
expect(viewSource).toContain('MotionZoneEditor')
expect(viewSource).not.toContain('AI 模型 3')
```

- [ ] **Step 2: Verify RED**

```bash
cd frontend
npm test -- eventDetectionPlatform.test.ts eventDetectionState.test.ts
```

- [ ] **Step 3: Implement camera rail and query selection**

```ts
const selectedCameraId = computed(() =>
  cameraIdFromDetectionQuery(route.query.camera_id),
)

function selectCamera(cameraId: number) {
  void router.replace({
    path: '/event-detection',
    query: { camera_id: String(cameraId) },
  })
}
```

After `/api/cameras` load: absent query -> first enabled camera, otherwise first camera; invalid/missing ID -> one warning then replace with fallback camera.

- [ ] **Step 4: Guard fast camera switching against stale requests**

```ts
let loadToken = 0

async function loadSelectedCamera(cameraId: number) {
  const token = ++loadToken
  const { data } = await axios.get<EventDetectionOverview>(
    `/api/cameras/${cameraId}/event-detection`,
  )
  if (token !== loadToken) return
  overview.value = data
}
```

Load `local.motion` source detail after overview and apply the same token guard.

- [ ] **Step 5: Implement center preview and zone editor**

Preview is opt-in; no camera-list row opens a stream. The selected preview uses:

```ts
const previewSrc = computed(() =>
  `/api/cameras/${selectedCameraId.value}/preview.mjpeg?stream=auto&t=${previewNonce.value}`,
)
```

Reuse `MotionZoneEditor` and exact existing zone APIs:

```text
POST   /api/cameras/{id}/motion-zones
PUT    /api/cameras/{id}/motion-zones/{zone_id}
DELETE /api/cameras/{id}/motion-zones/{zone_id}
```

Zone writes immediately persist, then reload selected source detail only.

- [ ] **Step 6: Render capability/source rail honestly**

`local.motion` can be configured. `person`, `vehicle`, and `intrusion` capability cards are disabled whenever status is `unavailable|unsupported|error`, display API `reason`, and have no toggle that can POST/PUT them.

- [ ] **Step 7: Implement explicit motion save/reset**

```ts
savedDraft.value = motionDraftFromSource(source)
draft.value = structuredClone(savedDraft.value)
```

Save:

```ts
const { data } = await axios.put<EventSourceRead>(
  `/api/cameras/${cameraId}/event-detection/sources/local.motion`,
  serializeMotionSourcePayload(draft.value),
)
savedDraft.value = motionDraftFromSource(data)
draft.value = structuredClone(savedDraft.value)
```

On save error, keep the dirty draft and show the server error; do not reload and discard edits.

- [ ] **Step 8: Add unsaved-change protection**

Before switching selected camera or leaving `/event-detection`, confirm only when `countMotionDraftChanges(saved, draft) > 0`. Browser `beforeunload` uses the same dirty predicate. Zone mutations are excluded because they are already persisted.

- [ ] **Step 9: Add approved layout CSS and global import**

`frontend/src/main.ts` imports:

```ts
import './styles/event-detection.css'
```

Base layout:

```css
.event-detection-page {
  display: grid;
  grid-template-columns: 250px minmax(480px, 1fr) 320px;
  min-height: calc(100vh - 88px);
  background: var(--nvr-bg);
}
```

Use only existing NVR tokens. At `max-width: 1180px`, move the right capability panel below center content; at `max-width: 760px`, stack camera rail, preview, and settings vertically.

- [ ] **Step 10: Run focused frontend validation**

```bash
cd frontend
npm test -- eventDetectionPlatform.test.ts eventDetectionState.test.ts motionZones.test.ts
npm run lint
npm run build
```

- [ ] **Step 11: Commit**

```bash
git add frontend/src/EventDetectionView.vue frontend/src/styles/event-detection.css frontend/src/main.ts frontend/src/event-detection frontend/src/eventDetectionPlatform.test.ts frontend/src/eventDetectionState.test.ts
git commit -m "feat: build event detection workspace"
```

---

### Task 7: Slim Camera Drawer to Event Detection Summary + Deep Link

**Files:**
- Modify: `frontend/src/CamerasWorkspace.vue`
- Modify: `frontend/src/cameraMotionPortal.test.ts`
- Modify: `frontend/src/cameraDetailDrawerV2.test.ts`
- Delete after reference check: `frontend/src/MotionDetectionPanel.vue`
- Delete after reference check: `frontend/src/MotionDetectionPanel.test.ts`

**Interfaces:**
- Camera drawer no longer mounts the full detector editor.
- Camera drawer shows current local-motion state and links to `eventDetectionRoute(cameraId)`.
- Playback/recording shortcuts stay intact.

- [ ] **Step 1: Rewrite portal test as RED summary/deep-link contract**

```ts
expect(workspaceSource).not.toContain('<MotionDetectionPanel')
expect(workspaceSource).toContain('事件检测')
expect(workspaceSource).toContain('eventDetectionRoute')
expect(workspaceSource).toContain('camera_id')
```

- [ ] **Step 2: Verify RED**

```bash
cd frontend
npm test -- cameraMotionPortal.test.ts cameraDetailDrawerV2.test.ts
```

- [ ] **Step 3: Replace full Teleport editor with compact summary**

Remove the `MotionDetectionPanel` import/mount. Add a small selected-camera overview request to `/api/cameras/{id}/event-detection` and display:

```text
事件检测
本地移动检测 · 检测中 / 已关闭 / 异常
前往配置 →
```

Navigation uses:

```ts
void router.push(eventDetectionRoute(selectedCameraId.value))
```

- [ ] **Step 4: Remove dead full-panel files only after exact reference check**

Run:

```bash
cd frontend
rg "MotionDetectionPanel" src
```

Expected after the workspace change: only the component and its own test reference the name. Then delete those two files. Preserve `MotionZoneEditor.vue`, `utils/motionZones.ts`, and `motionZones.test.ts`.

- [ ] **Step 5: Run camera + detection regression tests**

```bash
cd frontend
npm test -- cameraMotionPortal.test.ts cameraDetailDrawerV2.test.ts eventDetectionPlatform.test.ts motionZones.test.ts
```

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src/CamerasWorkspace.vue frontend/src/cameraMotionPortal.test.ts frontend/src/cameraDetailDrawerV2.test.ts frontend/src/MotionDetectionPanel.vue frontend/src/MotionDetectionPanel.test.ts
git commit -m "refactor: move motion settings to event detection"
```

---

### Task 8: Full Regression, Migration Compatibility, Docker Smoke, Draft PR

**Files:** no planned feature additions; only real regression fixes are allowed.

**Interfaces:** final branch preserves legacy motion APIs/playback while adding the new platform and deployable frontend.

- [ ] **Step 1: Backend full verification**

```bash
cd backend
uv run python -m compileall app
uv run pytest
```

Expected: all backend tests pass.

- [ ] **Step 2: Frontend full verification**

```bash
cd frontend
npm run lint
npm test
npm run build
```

Expected: lint 0 errors; all Vitest tests pass; `vue-tsc` and Vite production build succeed through the existing build script.

- [ ] **Step 3: Migration compatibility check**

```bash
cd backend
uv run alembic upgrade head
uv run alembic current
```

Expected revision: `20260915_0017`. Verify an existing camera reads `connection_type="manual_rtsp"`; existing `motion_detection_settings`, `motion_zones`, and `motion_events` rows remain present.

- [ ] **Step 4: Docker Compose smoke**

```bash
docker compose config
docker compose build backend frontend
docker compose up -d backend frontend
```

Verify:

```bash
curl -fsS http://localhost:${FRONTEND_PORT:-8080}/api/health
curl -fsS http://localhost:${FRONTEND_PORT:-8080}/event-detection >/dev/null
```

Run the repository CI's backend-internal-only check, frontend API proxy check, and upload websocket proxy check using `.github/workflows/ci.yml` commands unchanged. Cleanup always runs:

```bash
docker compose down -v --remove-orphans
```

- [ ] **Step 5: Scope review**

```bash
git diff main...HEAD -- backend/app/models backend/migrations backend/app/services frontend/src
```

Confirm there is no motion-table rename, ONVIF client dependency, AI model dependency, fake smart-event toggle, or unrelated settings/health/playback redesign.

- [ ] **Step 6: Open Draft PR**

Title:

```text
feat: Event Detection Platform V1
```

Body bullets:

```text
- first-class /event-detection workspace
- local.motion behind generic Event Source registry
- normalized DetectionEvent API
- persisted camera connection_type with manual_rtsp compatibility
- Device Adapter + Stream Resolver boundaries for future ONVIF
- camera drawer reduced to event-detection summary/deep link
- ONVIF/AI capability slots remain unavailable by design in V1
```

- [ ] **Step 7: Verify PR CI**

All required PR checks must be green. Fix real failures with the narrowest failing test first, then rerun the affected full suite. Do not create empty commits to trigger verification.

- [ ] **Step 8: Final branch review**

```bash
git status --short
git log --oneline main..HEAD
git diff --check main...HEAD
```

Expected: clean status, only intentional feature commits, no whitespace errors.
