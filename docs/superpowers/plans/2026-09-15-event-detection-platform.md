# Event Detection Platform V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-class Event Detection workspace that keeps the existing local motion detector working while introducing stable Device Adapter, Stream Resolver, Event Source Registry, normalized DetectionEvent, and ONVIF-native-event extension boundaries.

**Architecture:** Keep the existing `motion_*` persistence and runtime as the first concrete provider, wrap it behind a generic event-source adapter, and expose new aggregate APIs under `/api/cameras/{id}/event-detection`. Add `connection_type` and a stream-resolution layer so recording, preview, and local motion detection stop depending directly on RTSP fields. The frontend gains a standalone `/event-detection` workspace; camera details retain only a compact status/deep-link card.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, asyncio, FFmpeg, Vue 3, TypeScript, Pinia, Vue Router, Element Plus, Vitest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-15-event-detection-platform-design.md`

## Global Constraints

- V1 implements only `manual_rtsp` devices and the real `local.motion` event source.
- `onvif`, `local.ai`, person, vehicle, intrusion, loitering, and other future capabilities must not be presented as working features.
- Do not rename or migrate `motion_detection_settings`, `motion_zones`, or `motion_events` in this change.
- Preserve existing `/api/cameras/{id}/motion-detection`, motion-zone APIs, `/api/motion-events`, playback timeline behavior, and stored data.
- `connection_type` is persisted in V1; historical cameras and normal camera creation resolve to `manual_rtsp`.
- Normal camera creation must not accept a fake working ONVIF camera before the ONVIF protocol implementation exists.
- Recording, preview, and local motion detection must use the new Stream Resolver boundary.
- Zone create/update/toggle/delete remains immediately persisted; ordinary detector parameters use draft + explicit save in the new workspace.
- Existing event-center semantics remain separate from event-detection configuration.
- Final handoff requires frontend lint/test/build, backend full pytest/compileall, and Docker smoke green.

---

## File Structure

### Backend files to create

- `backend/migrations/versions/20260915_0017_camera_connection_type.py` — adds/backfills `cameras.connection_type`.
- `backend/app/services/device_adapter.py` — device-source protocol plus V1 manual RTSP adapter.
- `backend/app/services/stream_resolver.py` — purpose-based stream resolution shared by recorder, preview, and detector.
- `backend/app/schemas/event_detection.py` — generic descriptors, config, overview, and `DetectionEventRead` DTOs.
- `backend/app/services/event_detection/registry.py` — provider registry and lookup.
- `backend/app/services/event_detection/motion_source.py` — adapter from legacy motion settings/runtime/events to generic contracts.
- `backend/app/services/event_detection/__init__.py` — default registry assembly.
- `backend/app/api/event_detection.py` — aggregate configuration/source/event endpoints.
- `backend/tests/test_camera_connection_type.py` — migration/API/model compatibility.
- `backend/tests/test_stream_resolver.py` — recording/preview/detection stream policy.
- `backend/tests/test_event_detection_registry.py` — registry and local motion descriptor/config mapping.
- `backend/tests/test_event_detection_api.py` — aggregate APIs and normalized event query.

### Backend files to modify

- `backend/app/models/camera.py` — persisted `connection_type`.
- `backend/app/schemas/camera.py` — read exposure and create/update guardrails.
- `backend/app/api/cameras.py` — use resolver for preview and preserve manual creation semantics.
- `backend/app/services/camera_config.py` — create recorder runtime config from resolved stream instead of raw path.
- `backend/app/services/ffmpeg_builder.py` — consume resolved stream URI/connection properties rather than rebuild from `camera.rtsp_path`.
- `backend/app/services/camera_preview.py` — consume resolved stream instead of owning main/sub selection.
- `backend/app/services/motion_manager.py` (or the current file that starts detector FFmpeg sessions) — request `purpose="detection"` from resolver.
- `backend/app/api/__init__.py` / `backend/app/main.py` — register the new event-detection router following current router registration style.
- Existing camera/preview/FFmpeg/motion tests — update expectations only where the stream-resolution boundary intentionally changes internal calls.

### Frontend files to create

- `frontend/src/EventDetectionView.vue` — standalone three-column event-detection workspace.
- `frontend/src/event-detection/types.ts` — API DTO TypeScript types.
- `frontend/src/event-detection/state.ts` — selected camera, draft normalization, dirty comparison, labels.
- `frontend/src/eventDetectionPlatform.test.ts` — workspace/navigation/capability contract tests.
- `frontend/src/eventDetectionState.test.ts` — pure state/draft tests.
- `frontend/src/styles/event-detection.css` — page layout matching the approved mockup and existing NVR tokens.

### Frontend files to modify

- `frontend/src/router.ts` — `/event-detection` route with `navKey: 'detection'`.
- `frontend/src/WorkspaceRoute.vue` — lazy-load/render `EventDetectionView`.
- `frontend/src/Root.vue` — main navigation entry “事件检测”.
- `frontend/src/navigation.ts` / `navigation.test.ts` — `eventDetectionRoute(cameraId?)` deep-link helper.
- `frontend/src/CamerasWorkspace.vue` — remove full motion portal and add compact event-detection summary portal.
- `frontend/src/cameraMotionPortal.test.ts` — migrate legacy expectations to compact deep-link summary semantics.
- `frontend/src/main.ts` — import the new stylesheet if global stylesheet registration is centralized there.

---

### Task 1: Persist Camera Connection Type Without Enabling Fake ONVIF

**Files:**
- Create: `backend/migrations/versions/20260915_0017_camera_connection_type.py`
- Modify: `backend/app/models/camera.py`
- Modify: `backend/app/schemas/camera.py`
- Test: `backend/tests/test_camera_connection_type.py`
- Test/adjust: `backend/tests/test_camera_batch.py`

**Interfaces:**
- Produces model field: `Camera.connection_type: str` with value `manual_rtsp` in V1.
- Produces API field: `CameraRead.connection_type: Literal['manual_rtsp', 'onvif']`.
- `CameraCreate` defaults to `manual_rtsp` and rejects `onvif` with validation error until the protocol path exists.
- Later Device Adapter selection consumes `camera.connection_type`.

- [ ] **Step 1: Write failing model/schema/API tests**

```python
# backend/tests/test_camera_connection_type.py
from app.schemas.camera import CameraCreate


def test_camera_create_defaults_to_manual_rtsp():
    payload = CameraCreate(
        name="gate",
        ip="10.0.0.10",
        username="admin",
        password="secret",
        rtsp_path="/main",
    )
    assert payload.connection_type == "manual_rtsp"


def test_camera_create_rejects_unimplemented_onvif():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CameraCreate(
            name="onvif-gate",
            connection_type="onvif",
            ip="10.0.0.11",
            username="admin",
            password="secret",
            rtsp_path="/main",
        )
```

Add an API/read assertion using the existing camera fixture style:

```python
assert response.json()[0]["connection_type"] == "manual_rtsp"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
cd backend
uv run pytest tests/test_camera_connection_type.py tests/test_camera_batch.py -q
```

Expected: failure because `connection_type` does not exist yet.

- [ ] **Step 3: Add model/schema field and migration**

Model shape:

```python
connection_type: Mapped[str] = mapped_column(
    String(32),
    default="manual_rtsp",
    server_default="manual_rtsp",
    nullable=False,
)
```

Schema shape:

```python
CameraConnectionType = Literal["manual_rtsp", "onvif"]

class CameraBase(BaseModel):
    connection_type: CameraConnectionType = "manual_rtsp"

    @model_validator(mode="after")
    def reject_unimplemented_onvif(self):
        if self.connection_type != "manual_rtsp":
            raise ValueError("ONVIF camera creation is not available yet")
        return self
```

Do not put this validator on `CameraRead`; reads must be able to represent future `onvif` rows. Prefer placing the create guard specifically on `CameraCreate` (and `CameraUpdate` if exposing mutation of the field).

Migration shape:

```python
def upgrade() -> None:
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
    op.drop_column("cameras", "connection_type")
```

Set `down_revision` to `20260915_0016` using the exact revision identifier from the current migration file.

- [ ] **Step 4: Run focused tests and migration upgrade**

```bash
cd backend
uv run pytest tests/test_camera_connection_type.py tests/test_camera_batch.py -q
uv run alembic upgrade head
```

Expected: PASS; existing rows read as `manual_rtsp`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/camera.py backend/app/schemas/camera.py backend/migrations/versions/20260915_0017_camera_connection_type.py backend/tests/test_camera_connection_type.py backend/tests/test_camera_batch.py
git commit -m "feat: add camera connection type"
```

---

### Task 2: Introduce Device Adapter and Stream Resolver, Then Migrate All Three Stream Consumers

**Files:**
- Create: `backend/app/services/device_adapter.py`
- Create: `backend/app/services/stream_resolver.py`
- Modify: `backend/app/services/camera_config.py`
- Modify: `backend/app/services/ffmpeg_builder.py`
- Modify: `backend/app/services/camera_preview.py`
- Modify: `backend/app/api/cameras.py`
- Modify: `backend/app/services/motion_manager.py` (or actual detector-session file discovered during execution)
- Test: `backend/tests/test_stream_resolver.py`
- Test/adjust: `backend/tests/test_camera_preview.py`
- Test/adjust: `backend/tests/test_ffmpeg_builder.py`
- Test/adjust: existing motion detector manager tests

**Interfaces:**
- Produces `StreamPurpose = Literal['recording', 'preview', 'detection']`.
- Produces `ResolvedStream` containing `uri`, `role`, and protocol-neutral metadata.
- Produces `resolve_stream(camera: Camera, purpose: StreamPurpose, *, preferred: Literal['auto','main','sub']='auto') -> ResolvedStream`.
- Recorder, preview API, and motion detector all consume this function.

- [ ] **Step 1: Write resolver policy tests**

```python
from app.services.stream_resolver import resolve_stream


def test_manual_rtsp_recording_uses_main(camera):
    camera.connection_type = "manual_rtsp"
    camera.rtsp_path = "/ch1/main"
    camera.sub_rtsp_path = "/ch1/sub"
    stream = resolve_stream(camera, "recording")
    assert stream.role == "main"
    assert "/ch1/main" in stream.uri


def test_manual_rtsp_detection_prefers_sub(camera):
    camera.connection_type = "manual_rtsp"
    camera.rtsp_path = "/ch1/main"
    camera.sub_rtsp_path = "/ch1/sub"
    stream = resolve_stream(camera, "detection")
    assert stream.role == "sub"
    assert "/ch1/sub" in stream.uri


def test_manual_rtsp_detection_falls_back_to_main(camera):
    camera.connection_type = "manual_rtsp"
    camera.rtsp_path = "/stream"
    camera.sub_rtsp_path = None
    stream = resolve_stream(camera, "detection")
    assert stream.role == "main"
```

Also assert an `onvif` camera raises a deliberate unsupported-adapter error, not an AttributeError or accidental RTSP fallback.

- [ ] **Step 2: Run resolver tests and verify RED**

```bash
cd backend
uv run pytest tests/test_stream_resolver.py -q
```

Expected: import/function failures.

- [ ] **Step 3: Implement the V1 manual device adapter**

Use focused protocol-neutral structures:

```python
# backend/app/services/device_adapter.py
from dataclasses import dataclass
from typing import Literal, Protocol

StreamRole = Literal["main", "sub"]
StreamPurpose = Literal["recording", "preview", "detection"]

@dataclass(slots=True, frozen=True)
class ResolvedStream:
    uri: str
    role: StreamRole
    purpose: StreamPurpose

class DeviceAdapter(Protocol):
    def resolve_stream(self, camera, purpose: StreamPurpose, *, preferred: str = "auto") -> ResolvedStream: ...
```

`ManualRtspDeviceAdapter` may reuse `build_rtsp_url()` and existing substream inference. Keep credential decryption in a single explicit place; do not duplicate URL-building logic across resolver consumers.

- [ ] **Step 4: Implement central resolver dispatch**

```python
# backend/app/services/stream_resolver.py
_manual = ManualRtspDeviceAdapter()


def resolve_stream(camera, purpose, *, preferred="auto"):
    if camera.connection_type == "manual_rtsp":
        return _manual.resolve_stream(camera, purpose, preferred=preferred)
    raise UnsupportedDeviceAdapter(f"connection type {camera.connection_type} is not implemented")
```

For `preview`, preserve explicit `stream=main|sub|auto`; for `recording`, force main; for `detection`, prefer sub then infer common `/main -> /sub` then fall back to main.

- [ ] **Step 5: Migrate preview path selection**

In `backend/app/api/cameras.py`, replace direct `resolve_preview_path(main_path=..., sub_path=...)` ownership with:

```python
resolved = resolve_stream(camera, "preview", preferred=stream)
```

Pass `resolved.uri` into the preview FFmpeg builder/session. Remove only duplicate path-selection responsibilities from `camera_preview.py`; keep process/timeout/MJPEG responsibilities there.

- [ ] **Step 6: Migrate recording input**

Change recorder config to carry the resolved URI rather than raw RTSP path components used solely to rebuild the URI:

```python
@dataclass(slots=True)
class CameraRuntimeConfig:
    id: int
    name: str
    stream_uri: str
    timestamp_mode: str
    # existing media timing fields remain
```

`runtime_config(camera, ...)` calls `resolve_stream(camera, "recording")`. `build_record_command()` uses `camera.stream_uri` directly for `-i`.

- [ ] **Step 7: Migrate local motion detector input**

At the point where detector runtime currently chooses main/sub paths, replace that decision with:

```python
resolved = resolve_stream(camera, "detection")
```

Preserve existing motion runtime `stream` reporting by mapping `resolved.role` to `main|sub`.

- [ ] **Step 8: Run all stream-consumer tests**

```bash
cd backend
uv run pytest tests/test_stream_resolver.py tests/test_camera_preview.py tests/test_ffmpeg_builder.py tests/test_motion_detection.py -q
```

If the motion test filename differs, run the existing test file(s) that exercise `motion_manager` startup/runtime.

Expected: PASS with unchanged externally visible recording/preview/motion behavior.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/device_adapter.py backend/app/services/stream_resolver.py backend/app/services/camera_config.py backend/app/services/ffmpeg_builder.py backend/app/services/camera_preview.py backend/app/api/cameras.py backend/app/services/motion_manager.py backend/tests/test_stream_resolver.py backend/tests/test_camera_preview.py backend/tests/test_ffmpeg_builder.py backend/tests
git commit -m "refactor: resolve camera streams by purpose"
```

---

### Task 3: Build Generic Event Source Contracts and Register Legacy Motion as the First Provider

**Files:**
- Create: `backend/app/schemas/event_detection.py`
- Create: `backend/app/services/event_detection/registry.py`
- Create: `backend/app/services/event_detection/motion_source.py`
- Create: `backend/app/services/event_detection/__init__.py`
- Test: `backend/tests/test_event_detection_registry.py`

**Interfaces:**
- Produces `EventSourceDescriptor`, `EventDetectionOverview`, `DetectionEventRead`.
- Produces `EventSourceAdapter` protocol with descriptor/config/update/runtime methods.
- Produces registry functions `get_event_source(source_id)` and `list_event_sources(camera, db)`.
- Registers only `local.motion` as a configurable real source in V1.
- Produces static unavailable capability slots for `local.ai`/future smart detection only in the overview layer, never as writable providers.

- [ ] **Step 1: Write RED registry/descriptor tests**

```python
def test_default_registry_has_only_real_motion_provider():
    from app.services.event_detection import event_source_registry
    assert event_source_registry.ids() == ["local.motion"]


def test_motion_descriptor_is_local_and_motion_only(camera, db_session):
    descriptor = local_motion_source.descriptor(camera, db_session)
    assert descriptor.id == "local.motion"
    assert descriptor.source_kind == "local"
    assert descriptor.provider == "motion"
    assert descriptor.capabilities == ["motion"]
    assert descriptor.configurable is True
```

Add mapping assertions for disabled/running/error runtime states based on existing `motion_detection_manager.status()` behavior.

- [ ] **Step 2: Run and verify RED**

```bash
cd backend
uv run pytest tests/test_event_detection_registry.py -q
```

- [ ] **Step 3: Define strict Pydantic DTOs**

Use literals that match the spec:

```python
EventSourceKind = Literal["local", "camera_native"]
EventSourceStatus = Literal["available", "unavailable", "unsupported", "error"]
DetectionEventType = Literal["motion", "person", "vehicle", "intrusion", "tamper", "digital_input", "unknown"]

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
```

Define a generic source detail wrapper whose `config` is a JSON-compatible dict in V1 so future providers can own different schemas without bloating one global model:

```python
class EventSourceRead(BaseModel):
    descriptor: EventSourceDescriptor
    config: dict[str, object]
    zones: list[MotionZoneRead] = Field(default_factory=list)
```

- [ ] **Step 4: Implement registry protocol and default registry**

```python
class EventSourceAdapter(Protocol):
    source_id: str
    async def descriptor(self, camera: Camera, db: AsyncSession) -> EventSourceDescriptor: ...
    async def read(self, camera: Camera, db: AsyncSession) -> EventSourceRead: ...
    async def update(self, camera: Camera, payload: dict[str, object], db: AsyncSession) -> EventSourceRead: ...
```

Registry rejects duplicate IDs at registration and raises a domain `UnknownEventSource` for unknown IDs.

- [ ] **Step 5: Implement `LocalMotionEventSource` as a bridge, not a duplicate**

Extract reusable internal functions from `backend/app/api/motion_detection.py` if necessary, e.g. a service module function:

```python
async def read_motion_detection(camera_id: int, db: AsyncSession) -> MotionDetectionRead: ...
async def update_motion_detection(camera_id: int, payload: MotionDetectionUpdate, db: AsyncSession) -> MotionDetectionRead: ...
```

Both legacy API and `LocalMotionEventSource` must call these same service functions. Do not duplicate persistence/restart behavior.

Map config keys exactly:

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

- [ ] **Step 6: Run registry and legacy motion tests**

```bash
cd backend
uv run pytest tests/test_event_detection_registry.py tests/test_motion_detection.py -q
```

Expected: both generic bridge tests and existing legacy API tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/event_detection.py backend/app/services/event_detection backend/app/api/motion_detection.py backend/app/services backend/tests/test_event_detection_registry.py backend/tests/test_motion_detection.py
git commit -m "feat: add event source registry"
```

---

### Task 4: Expose Aggregate Event Detection APIs and Normalized Detection Events

**Files:**
- Create: `backend/app/api/event_detection.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_event_detection_api.py`

**Interfaces:**
- `GET /api/cameras/{id}/event-detection`
- `GET /api/cameras/{id}/event-detection/sources/{source_id}`
- `PUT /api/cameras/{id}/event-detection/sources/{source_id}`
- `GET /api/detection-events?start=&end=&camera_id=&event_type=&provider=`
- Legacy motion APIs remain untouched externally.

- [ ] **Step 1: Write failing API tests**

Overview test:

```python
response = client.get(f"/api/cameras/{camera_id}/event-detection")
assert response.status_code == 200
body = response.json()
assert body["camera"]["id"] == camera_id
assert any(source["id"] == "local.motion" for source in body["sources"])
assert any(item["event_type"] == "person" and item["status"] == "unavailable" for item in body["capability_slots"])
```

Source update test:

```python
response = client.put(
    f"/api/cameras/{camera_id}/event-detection/sources/local.motion",
    json={"enabled": True, "sensitivity": "high", "analysis_fps": 5, "analysis_width": 640,
          "min_duration_ms": 800, "merge_gap_ms": 10000, "event_min_interval_ms": 60000},
)
assert response.status_code == 200
assert response.json()["config"]["enabled"] is True
```

Unknown/future provider behavior:

```python
assert client.get(f"/api/cameras/{camera_id}/event-detection/sources/camera.onvif").status_code in {404, 409, 501}
```

Choose one status contract during implementation and assert it consistently; recommendation: `404` for unregistered source ID, while overview descriptors explain future unavailable capabilities.

- [ ] **Step 2: Run and verify RED**

```bash
cd backend
uv run pytest tests/test_event_detection_api.py -q
```

- [ ] **Step 3: Implement camera overview**

Return:

```python
class EventDetectionOverview(BaseModel):
    camera: EventDetectionCameraSummary
    sources: list[EventSourceDescriptor]
    capability_slots: list[DetectionCapabilitySlot]
    enabled_source_ids: list[str]
```

V1 capability slots must be honest:

```python
[
    {"event_type": "motion", "status": "available", "source_id": "local.motion"},
    {"event_type": "person", "status": "unavailable", "reason": "未安装 AI Provider"},
    {"event_type": "vehicle", "status": "unavailable", "reason": "未安装 AI Provider"},
    {"event_type": "intrusion", "status": "unavailable", "reason": "尚无可用 Provider"},
]
```

- [ ] **Step 4: Implement generic source GET/PUT**

Resolve the camera first, then registry adapter, then delegate:

```python
adapter = event_source_registry.get(source_id)
return await adapter.update(camera, payload, db)
```

Validate the local-motion payload through `MotionDetectionUpdate.model_validate(payload)` inside the motion adapter before writing.

- [ ] **Step 5: Implement normalized detection-event query**

For V1 query `MotionEvent`, then map each row:

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
    snapshot_url=f"/api/motion-events/{event.id}/snapshot" if event.snapshot_path else None,
    metadata=parse_legacy_metadata(event.metadata_json),
)
```

`provider` and `event_type` filters return zero rows for unsupported values in V1 rather than relabeling motion events.

- [ ] **Step 6: Run API + existing motion-event tests**

```bash
cd backend
uv run pytest tests/test_event_detection_api.py tests/test_motion_detection.py tests/test_event_motion_websocket.py tests/test_event_timezone.py -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/event_detection.py backend/app/api/__init__.py backend/app/main.py backend/app/schemas/event_detection.py backend/tests/test_event_detection_api.py
git commit -m "feat: expose event detection api"
```

---

### Task 5: Add Frontend Route, Navigation Entry, and Typed Event Detection State

**Files:**
- Create: `frontend/src/event-detection/types.ts`
- Create: `frontend/src/event-detection/state.ts`
- Create: `frontend/src/eventDetectionState.test.ts`
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/WorkspaceRoute.vue`
- Modify: `frontend/src/Root.vue`
- Modify: `frontend/src/navigation.ts`
- Modify: `frontend/src/navigation.test.ts`
- Create: `frontend/src/eventDetectionPlatform.test.ts`

**Interfaces:**
- Produces route `/event-detection` with `navKey: 'detection'`.
- Produces `eventDetectionRoute(cameraId?: number | null)`.
- Produces typed `EventDetectionOverview`, `EventSourceRead`, `MotionSourceDraft`.
- Produces pure helpers `cameraIdFromDetectionQuery`, `motionDraftFromSource`, `countMotionDraftChanges`, `serializeMotionSourcePayload`.

- [ ] **Step 1: Write route/navigation/state RED tests**

```ts
import { describe, expect, it } from 'vitest'
import { eventDetectionRoute } from './navigation'

it('builds an event detection camera deep link', () => {
  expect(eventDetectionRoute(12)).toEqual({ path: '/event-detection', query: { camera_id: '12' } })
})
```

State tests:

```ts
expect(cameraIdFromDetectionQuery('12')).toBe(12)
expect(cameraIdFromDetectionQuery('x')).toBeNull()
expect(serializeMotionSourcePayload(draft).analysis_fps).toBe(5)
expect(countMotionDraftChanges(saved, { ...saved, sensitivity: 'high' })).toBe(1)
```

Source-contract test should assert `Root.vue`, `router.ts`, and `WorkspaceRoute.vue` contain the new key/path/component and do not remove the existing `events` route.

- [ ] **Step 2: Run RED frontend tests**

```bash
cd frontend
npm test -- eventDetectionState.test.ts eventDetectionPlatform.test.ts navigation.test.ts
```

- [ ] **Step 3: Add TypeScript DTOs and pure state utilities**

Representative DTO:

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

Keep API transformation logic in `event-detection/state.ts`; do not bury it inside the Vue template.

- [ ] **Step 4: Add route + shell navigation**

Router record:

```ts
{ path: '/event-detection', name: 'event-detection', component: WorkspaceRoute, meta: { navKey: 'detection' } },
```

Root nav entry should sit in the core monitoring group near cameras/events according to the approved mockup:

```ts
{ key: 'detection', label: '事件检测', description: '移动检测与智能事件来源', target: '/event-detection', group: 'core', icon: markRaw(Aim) },
```

Use an Element Plus icon already available in the installed version; if `Aim` is unavailable, select a semantically suitable existing icon and keep the label/route exact.

- [ ] **Step 5: Run focused tests**

```bash
cd frontend
npm test -- eventDetectionState.test.ts eventDetectionPlatform.test.ts navigation.test.ts
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/event-detection frontend/src/eventDetectionState.test.ts frontend/src/eventDetectionPlatform.test.ts frontend/src/router.ts frontend/src/WorkspaceRoute.vue frontend/src/Root.vue frontend/src/navigation.ts frontend/src/navigation.test.ts
git commit -m "feat: add event detection navigation"
```

---

### Task 6: Build the Approved Event Detection Workspace and Reuse Motion Zone Editing

**Files:**
- Create: `frontend/src/EventDetectionView.vue`
- Create: `frontend/src/styles/event-detection.css`
- Modify: `frontend/src/main.ts`
- Reuse: `frontend/src/MotionZoneEditor.vue`
- Test: `frontend/src/eventDetectionPlatform.test.ts`
- Test: `frontend/src/eventDetectionState.test.ts`

**Interfaces:**
- Consumes `/api/cameras`, `/api/cameras/{id}/event-detection`, `/sources/local.motion`, and existing motion-zone endpoints.
- Consumes `/api/cameras/{id}/preview.mjpeg?stream=auto` for on-demand visual editing.
- Query `camera_id` is the durable selected-camera state.
- Parameter save is explicit; zone writes are immediate.

- [ ] **Step 1: Extend RED tests for approved UI semantics**

Assert source text/structure:

```ts
expect(view).toContain('事件检测')
expect(view).toContain('检测摄像头')
expect(view).toContain('检测区域')
expect(view).toContain('移动检测')
expect(view).toContain('未安装 AI Provider')
expect(view).toContain('保存设置')
expect(view).toContain('重置')
expect(view).not.toContain('AI 模型 3')
```

Also assert the workspace imports/reuses `MotionZoneEditor` rather than reimplementing polygon drawing.

- [ ] **Step 2: Run RED tests**

```bash
cd frontend
npm test -- eventDetectionPlatform.test.ts eventDetectionState.test.ts
```

- [ ] **Step 3: Implement camera rail and deep-link selection**

Behavior:

```ts
const selectedCameraId = computed(() => cameraIdFromDetectionQuery(route.query.camera_id))

function selectCamera(cameraId: number) {
  void router.replace({ path: '/event-detection', query: { camera_id: String(cameraId) } })
}
```

When query is absent, select the first enabled camera after load using `replace`, not `push`; when query points to a missing camera, show one warning and normalize to the first available camera.

- [ ] **Step 4: Implement overview and source loading with request-staleness guard**

Use a monotonically increasing request token so fast camera switching cannot paint stale source config:

```ts
let loadToken = 0
async function loadSelectedCamera() {
  const token = ++loadToken
  const { data } = await axios.get<EventDetectionOverview>(`/api/cameras/${id}/event-detection`)
  if (token !== loadToken) return
  overview.value = data
}
```

- [ ] **Step 5: Implement center preview + zones**

Preview remains opt-in. Do not start a permanent MJPEG connection for every camera row. For the selected camera, show a play control; start `/api/cameras/{id}/preview.mjpeg?stream=auto` only after user action or when entering zone-edit mode if the approved existing zone editor requires a frame.

Reuse zone CRUD URLs exactly:

```text
POST   /api/cameras/{id}/motion-zones
PUT    /api/cameras/{id}/motion-zones/{zone_id}
DELETE /api/cameras/{id}/motion-zones/{zone_id}
```

After zone mutation, reload only the selected source/overview; do not reload the entire camera inventory unnecessarily.

- [ ] **Step 6: Implement right capability/source rail honestly**

Render descriptors/slots from API. `local.motion` is active/configurable. `person`, `vehicle`, and `intrusion` cards are disabled when API says unavailable/unsupported and show `reason` text. There are no clickable fake switches for unavailable providers.

- [ ] **Step 7: Implement motion source draft + explicit save/reset**

On source load:

```ts
savedDraft.value = motionDraftFromSource(source)
draft.value = structuredClone(savedDraft.value)
```

Save:

```ts
await axios.put(
  `/api/cameras/${cameraId}/event-detection/sources/local.motion`,
  serializeMotionSourcePayload(draft.value),
)
```

After success, replace both saved and current draft from returned server data. If save fails, preserve the current draft and show the server error; do not silently reload/discard edits.

- [ ] **Step 8: Implement unsaved-change protection for camera switch and route leave**

Before selecting another camera or leaving `/event-detection`, confirm only when `countMotionDraftChanges(...) > 0`. Zone mutations do not participate in draft dirty count because they are already persisted.

- [ ] **Step 9: Match approved visual structure using existing tokens**

CSS layout:

```css
.event-detection-page {
  display: grid;
  grid-template-columns: 250px minmax(480px, 1fr) 320px;
  min-height: calc(100vh - 88px);
}
```

Use `var(--nvr-bg)`, `var(--nvr-surface)`, `var(--nvr-border)`, `var(--nvr-text)`, `var(--nvr-blue)` and existing responsive conventions. At narrower widths collapse the right rail below the preview; on mobile stack all panels. Do not introduce a separate design system.

- [ ] **Step 10: Run focused tests, typecheck, build**

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

### Task 7: Remove Full Motion Configuration From Camera Drawer and Replace It With a Compact Event Detection Summary

**Files:**
- Modify: `frontend/src/CamerasWorkspace.vue`
- Modify: `frontend/src/cameraMotionPortal.test.ts`
- Modify or delete only if no longer referenced: `frontend/src/MotionDetectionPanel.vue`
- Modify or delete only if no longer referenced: `frontend/src/MotionDetectionPanel.test.ts`
- Test: `frontend/src/cameraDetailDrawerV2.test.ts`

**Interfaces:**
- Camera drawer no longer hosts the full motion settings/editor.
- Camera drawer presents a summary and links to `/event-detection?camera_id=<id>`.
- Existing camera playback/recording shortcuts stay intact.

- [ ] **Step 1: Rewrite legacy portal test as RED summary/deep-link test**

Assert:

```ts
expect(workspace).not.toContain('<MotionDetectionPanel')
expect(workspace).toContain('事件检测')
expect(workspace).toContain('/event-detection')
expect(workspace).toContain('camera_id')
```

The component may fetch the generic overview for the selected camera or use a small summary subcomponent; it must not mount the full detector editor.

- [ ] **Step 2: Run RED tests**

```bash
cd frontend
npm test -- cameraMotionPortal.test.ts cameraDetailDrawerV2.test.ts
```

- [ ] **Step 3: Replace the Teleported full panel**

Remove:

```vue
<MotionDetectionPanel :key="selectedCameraId" :camera-id="selectedCameraId" />
```

Add a compact card with:

```text
事件检测
本地移动检测 · 检测中/已关闭/异常
前往配置 →
```

Use `eventDetectionRoute(selectedCameraId)` or equivalent router push; do not hardcode query assembly in multiple components.

- [ ] **Step 4: Remove dead full-panel code only after reference check**

Run:

```bash
cd frontend
rg "MotionDetectionPanel" src
```

If no production references remain, delete `MotionDetectionPanel.vue` and migrate/delete its component-specific tests while preserving `MotionZoneEditor.vue`, `motionZones.test.ts`, and generic motion behavior tests. If any legitimate production reference remains, keep the file; do not delete for cleanliness alone.

- [ ] **Step 5: Run camera + event detection frontend tests**

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

### Task 8: Regression Verification, Docker Smoke, and Reviewable PR

**Files:**
- No feature scope expansion.
- Modify tests/code only for real failures caused by the preceding changes.
- Create PR from `feat/event-detection-platform` to `main` after green verification.

**Interfaces:**
- Final branch preserves legacy motion APIs and playback behavior.
- New event detection APIs/workspace are deployable through the existing Docker Compose stack.

- [ ] **Step 1: Run backend compile and full test suite**

```bash
cd backend
uv run python -m compileall app
uv run pytest
```

Expected: all tests pass; no skipped regression is accepted as a substitute for fixing a failure.

- [ ] **Step 2: Run frontend full validation**

```bash
cd frontend
npm run lint
npm test
npm run build
```

Expected: lint 0 errors, all Vitest tests pass, `vue-tsc`/Vite production build succeeds through the existing build script.

- [ ] **Step 3: Run migration compatibility check on a database upgraded from the previous head**

At minimum:

```bash
cd backend
uv run alembic upgrade head
uv run alembic current
```

Verify an existing Camera row returns `connection_type="manual_rtsp"` and existing motion settings/events remain present.

- [ ] **Step 4: Run Docker Compose smoke using the repository CI-equivalent commands**

```bash
docker compose config
docker compose build backend frontend
docker compose up -d backend frontend
```

Then verify the same surfaces CI checks:

```bash
curl -fsS http://localhost:${FRONTEND_PORT:-8080}/api/health
curl -fsS http://localhost:${FRONTEND_PORT:-8080}/event-detection >/dev/null
```

Also verify the backend is not unexpectedly exposed directly and existing upload websocket proxy smoke still passes using the project’s existing CI commands/script. Always run cleanup:

```bash
docker compose down -v --remove-orphans
```

- [ ] **Step 5: Review diff for forbidden accidental scope**

Confirm:

```bash
git diff main...HEAD -- backend/app/models backend/migrations frontend/src
```

Must show no motion-table renames, no ONVIF client dependency, no AI model dependency, no fake working smart-event toggles, and no unrelated settings/health/playback redesign.

- [ ] **Step 6: Open a Draft PR**

Title:

```text
feat: Event Detection Platform V1
```

PR body must summarize:

```text
- first-class /event-detection workspace
- local.motion behind generic Event Source registry
- normalized DetectionEvent API
- persisted camera connection_type with manual_rtsp compatibility
- Device Adapter + Stream Resolver boundaries for future ONVIF
- camera drawer reduced to event-detection summary/deep link
- ONVIF/AI capability slots remain unavailable by design in V1
```

- [ ] **Step 7: Verify PR CI and fix real failures**

Do not mark ready or merge while any required check is red. For every fix, rerun the most specific local test first, then the affected full suite.

- [ ] **Step 8: Commit any final verified fixes**

Use specific messages such as:

```bash
git commit -m "fix: preserve preview stream selection"
git commit -m "fix: guard stale event detection loads"
```

Do not create empty verification commits.
