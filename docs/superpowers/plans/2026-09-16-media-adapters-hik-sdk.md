# Independent Media Adapters + HIK SDK Implementation Plan

> **Required workflow:** execute task-by-task with strict RED/GREEN coverage for backend/media changes. Keep deployment as `git pull && ./deploy.sh`.

**Goal:** Make `manual_rtsp`, `onvif`, and `hik_sdk` independently selectable media adapters while preserving one shared recording/preview/detection/event pipeline. HIK media is supplied by a separate Python HCNetSDK bridge and never silently falls back to RTSP.

**Architecture:** Introduce a transport-neutral `MediaSource` and registry selected strictly by `Camera.connection_type`. Manual and ONVIF resolve to RTSP media sources; HIK resolves to a bridge source. Media consumers call one common media-input boundary. A dedicated `hik_bridge` service owns HCNetSDK process lifecycle and real-play callbacks. HIK metadata is stored separately from camera credentials and ONVIF metadata.

**Tech stack:** FastAPI/Python 3.12, SQLAlchemy/Alembic, httpx, FFmpeg, Vue 3 + TypeScript, Docker Compose, Hikvision HCNetSDK Linux64 via `ctypes`.

---

## Task 1 — Establish the transport-neutral media contract

**Files:**
- Create: `backend/app/services/media_source.py`
- Create: `backend/app/services/media_adapter.py`
- Modify: `backend/app/services/device_adapter.py`
- Modify: `backend/app/services/onvif_device_adapter.py`
- Modify: `backend/app/services/stream_resolver.py`
- Modify: `backend/tests/test_stream_resolver.py`
- Create: `backend/tests/test_media_adapter.py`

**RED:** Add tests proving:
- registry selects `manual_rtsp`, `onvif`, and `hik_sdk` strictly by `connection_type`;
- unknown types raise `UnsupportedMediaAdapter`;
- no adapter fallback occurs;
- existing manual main/sub and ONVIF profile selection still produce the same credentialed RTSP URI;
- `MediaSource` validates RTSP and bridge payloads.

Run targeted tests and confirm the new imports/types fail before implementation.

**GREEN:**
- Add `MediaSource` with `adapter`, `transport`, `role`, `purpose`, `uri`, and optional bridge descriptor/session fields.
- Add `MediaAdapter` protocol and registry.
- Move the media responsibility out of the generic device concept: implement `ManualRtspMediaAdapter` and `OnvifMediaAdapter` while leaving compatibility aliases where needed.
- Add `resolve_media_source()`.
- Keep `resolve_stream()` as a compatibility wrapper that accepts only URI/RTSP sources and raises a clear error for non-URI transports.

**Verify:** targeted media-adapter tests pass; existing stream-resolver tests remain green.

---

## Task 2 — Make FFmpeg input transport-neutral without changing RTSP behavior

**Files:**
- Create: `backend/app/services/media_input.py`
- Modify: `backend/app/services/ffmpeg_builder.py`
- Modify: `backend/app/services/camera_config.py`
- Modify: `backend/app/services/recorder_manager.py`
- Modify: `backend/app/services/camera_preview.py`
- Modify: `backend/app/services/motion_worker.py`
- Modify: `backend/app/services/event_recording.py`
- Modify: `backend/tests/test_ffmpeg_builder.py`
- Modify/Create targeted tests for recorder/preview/motion/event media input behavior.

**RED:** Add tests that assert:
- RTSP input arguments remain `-rtsp_transport tcp ... -i <uri>`;
- consumers receive media through the shared input boundary, not a camera-type conditional;
- a bridge source produces a bridge input and lifecycle cleanup hook rather than RTSP flags;
- command redaction never logs credentials or bridge control secrets.

**GREEN:**
- Change runtime config from raw `stream_uri` ownership to a media-source/media-input representation.
- Centralize FFmpeg input argument construction.
- Preserve all current timestamp, segment, codec-copy, timeout, and reconnect behavior for RTSP.
- Introduce a lease abstraction for transports requiring setup/cleanup. Recorder, preview, motion detection and event prebuffer use the same boundary.
- Do not add `if connection_type == ...` inside those consumers.

**Verify:** targeted tests green; compile all backend modules.

---

## Task 3 — Persist HIK adapter metadata and validate camera type

**Files:**
- Create: `backend/app/models/hikvision.py`
- Modify: `backend/app/models/camera.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/20260916_0019_hik_device_metadata.py`
- Create: `backend/app/schemas/hikvision.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/tests/test_camera_connection_type.py`
- Create: `backend/tests/test_hik_models.py`

**RED:** Cover:
- `hik_sdk` is accepted as a camera connection type where adapter-specific APIs use it;
- generic manual camera creation still rejects adapter-specific types;
- one-to-one HIK metadata cascades on camera deletion;
- migration head becomes `20260916_0019` and downgrade removes only HIK metadata.

**GREEN:** Add `HikDeviceMetadata` fields:
- `camera_id` PK/FK cascade;
- `sdk_port` default 8000;
- `channel` default 1;
- `main_stream_type` default 0;
- `sub_stream_type` default 1;
- nullable `device_serial`, `device_model`, `device_name`;
- timestamps.

Keep username/password in the existing encrypted camera fields only.

**Verify:** model/migration tests green.

---

## Task 4 — Build a testable HCNetSDK Python bridge core

**Files:**
- Create: `hik_bridge/__init__.py`
- Create: `hik_bridge/hcnet_types.py`
- Create: `hik_bridge/sdk.py`
- Create: `hik_bridge/service.py`
- Create: `hik_bridge/tests/test_sdk_service.py`
- Create: `hik_bridge/pyproject.toml`

**RED:** With a fake SDK, test:
- init/cleanup exactly once per service lifecycle;
- probe logs in and logs out;
- RealPlay uses configured channel and main/sub stream type;
- callback bytes are emitted in callback order;
- queue is bounded and slow consumers are terminated rather than growing memory;
- session stop calls `NET_DVR_StopRealPlay` and logout;
- SDK error responses include numeric error code but never password.

**GREEN:**
- Define only the minimal HCNetSDK `ctypes` structures/prototypes needed for login, device info and RealPlay, guided by the supplied official Python demo.
- Load runtime from `HIK_SDK_PATH` / `/opt/hikvision` and configure component paths before `NET_DVR_Init` when supported.
- Expose an SDK protocol so unit tests never need proprietary `.so` files.
- Maintain callback objects for the full native session lifetime to avoid GC invalidating callbacks.
- Use bounded thread-safe queues and explicit close sentinels.

**Verify:** bridge unit tests green in fake/no-runtime mode.

---

## Task 5 — Expose the bridge as an internal service

**Files:**
- Create: `hik_bridge/app.py`
- Create: `hik_bridge/Dockerfile`
- Modify: `hik_bridge/pyproject.toml`
- Create: `hik_bridge/tests/test_api.py`

**RED:** API tests cover:
- `/health` works even when runtime is absent and reports `runtime_available=false`;
- `/probe` returns 503 with a sanitized message when runtime is absent;
- `/probe` returns device identity using a fake SDK;
- `POST /streams` creates an opaque id;
- `GET /streams/{id}/media` streams bytes;
- `DELETE /streams/{id}` is idempotent and releases SDK resources;
- no credentials appear in URLs or serialized responses.

**GREEN:** Implement FastAPI endpoints on an internal-only port. Stream output is `application/octet-stream`; stream ids are random opaque tokens. The media endpoint ends when HCNetSDK disconnects or the consumer is too slow.

**Verify:** bridge API tests green.

---

## Task 6 — Add backend HIK bridge client + HIK media adapter

**Files:**
- Create: `backend/app/services/hik_bridge_client.py`
- Create: `backend/app/services/hik_media_adapter.py`
- Modify: `backend/app/services/media_adapter.py`
- Modify: `backend/app/services/media_input.py`
- Create: `backend/tests/test_hik_media_adapter.py`
- Create: `backend/tests/test_hik_bridge_client.py`

**RED:** Cover:
- HIK camera resolves only through `hik_sdk` adapter;
- creating a lease sends host, SDK port, channel, stream type and credentials to the bridge control API;
- returned media URL contains only opaque stream id;
- recording chooses main stream type; preview/detection choose sub stream unless main explicitly requested;
- cleanup calls bridge DELETE exactly once;
- bridge errors propagate without RTSP fallback or credential leakage.

**GREEN:**
- Implement async httpx client to the internal bridge URL.
- Resolve HIK metadata and current camera credentials into an in-memory bridge request.
- Open a bridge stream in the media-input lease, expose its internal media endpoint to FFmpeg, and delete it on lease close.
- Configure FFmpeg bridge input without RTSP-only flags.

**Verify:** targeted adapter/client/input tests green.

---

## Task 7 — Add HIK camera probe/create/update API

**Files:**
- Create: `backend/app/api/hik_cameras.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/hikvision.py`
- Create: `backend/tests/test_hik_camera_api.py`

**RED:** Cover:
- `POST /api/cameras/hik/probe` validates host/port/user/password and uses bridge probe;
- `POST /api/cameras/hik` re-probes before create, persists `connection_type=hik_sdk`, encrypted password and HIK metadata;
- plaintext password never appears in DB metadata or response;
- duplicate camera identity/name handling matches existing API conventions;
- `PUT /api/cameras/hik/{camera_id}` rejects non-HIK cameras, re-probes, updates metadata, and restarts active media/recorder safely;
- missing bridge/runtime returns actionable 503, with no RTSP fallback.

**GREEN:** Implement HIK-specific router before generic `/api/cameras/{camera_id}` routes. Reuse existing encryption, media-info fields, motion restart, schedule reconcile and recorder handoff patterns from ONVIF update.

**Verify:** HIK API tests plus ONVIF API regressions green.

---

## Task 8 — Add explicit HIK UI alongside RTSP and ONVIF

**Files:**
- Create: `frontend/src/HikCameraAddView.vue`
- Modify: `frontend/src/CamerasWorkspace.vue`
- Create: `frontend/src/hikCameraIntegration.test.ts`
- Modify as needed: `frontend/src/stores/cameras.ts`, camera type definitions/display labels.

**RED/behavior tests:** Assert camera workspace exposes three explicit choices without auto-starting media:
- existing/manual RTSP path;
- `添加 ONVIF`;
- `添加 HIK-SDK`.

HIK dialog tests should protect probe → discovered identity → create → list refresh semantics and verify no preview/play request is triggered by opening or completing the form.

**GREEN:** Build a compact HIK form for host, SDK port (8000), username, password and channel (1). Probe first, show returned model/serial/name, then create. Match current camera workspace styling and manual-media-start policy.

**Verify:** frontend targeted tests, lint and build.

---

## Task 9 — Docker/deployment integration without committing proprietary binaries

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`
- Create: `vendor/hikvision/README.md`
- Modify: `.env.example`
- Modify: `deploy.sh`
- Modify: `.github/workflows/ci.yml`
- Add smoke assertions as needed.

**RED:** Extend CI/shell assertions to require:
- Compose contains internal `hik-bridge` service;
- backend receives bridge base URL;
- bridge health works without proprietary runtime;
- backend/frontend remain deployable when `vendor/hikvision` contains only README/empty runtime;
- migration head/table expectation is `0019` / `hik_device_metadata`.

**GREEN:**
- Add `hik-bridge` build/service with `expose`, healthcheck and no host port.
- Mount/read `./vendor/hikvision` at `/opt/hikvision`.
- Service starts in degraded/no-runtime mode if libraries are absent.
- Backend depends on bridge health but manual/ONVIF remain functional if runtime is unavailable.
- `deploy.sh` preserves the single command workflow and may detect/copy/extract a locally supplied SDK archive into ignored `vendor/hikvision/runtime` when present, without requiring extra commands.
- Ignore all vendor HIK binaries/archive payloads while keeping the README tracked.

**Verify:** shell syntax, compose config and docker smoke.

---

## Task 10 — Regression, security review, PR and merge

**Verification:**
1. Backend compileall + targeted tests.
2. Full backend pytest.
3. Bridge unit/API tests in no-runtime/fake mode.
4. Frontend lint/test/build.
5. Docker compose config + smoke.
6. Search production media consumers for adapter-specific branching; only registry/adapter/API layers may know `hik_sdk`.
7. Search committed content for SDK binaries and plaintext test credentials.
8. Review migration upgrade/downgrade and cascade behavior.
9. Review stream-session cleanup on normal stop, FFmpeg failure, client disconnect and bridge errors.
10. Confirm opening camera/HIK dialogs does not auto-start media.

Open one PR from `feat/media-adapters-hik-sdk` to `main`, run PR CI once, review the full diff, fix blockers, and merge directly when green in accordance with `AGENTS.md`. A second main CI is not required unless the merge itself changes code or picks up concurrent main changes.

**Delivery:** Final operational command remains:

```bash
git pull && ./deploy.sh
```
