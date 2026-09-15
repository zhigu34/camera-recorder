# Health Center V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor System Health into a problem-first diagnostic workspace backed by a cheap realtime contract and one unified 24h/72h reliability read model, while preserving manual media-start behavior and existing compatibility routes.

**Architecture:** Split health into two data products: a lightweight realtime snapshot used by the global runtime websocket/store, and a historical reliability builder used only by Health Center. Persist missing diagnostic evidence at the failure boundary, then compose the frontend from focused Health V3 components and a dedicated reliability store instead of one monolithic view and duplicate `trends`/`stability` requests.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, SQLite, Vue 3, TypeScript, Pinia, Vue Router, Element Plus, Vitest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-15-health-center-v3-design.md`

## Global Constraints

- Preserve `/health-center` as the user-facing route.
- Preserve manual media startup: Health navigation or drawer opening never starts preview/playback; only explicit playback actions may reuse the existing explicit-action semantics.
- `/ws/status` must not execute historical 24h Recording aggregation on each tick.
- Reliability is loaded only while Health is open or explicitly refreshed; 24h/72h responses are cached independently in the frontend.
- One reliability request must load each historical dataset once and must not call another high-level report function that re-queries the same period.
- Historical `online_rate` compatibility may remain on old endpoints, but the V3 contract uses `recorder_availability_rate`.
- Every counted recording gap must expose non-empty `cause`, `detail`, and `confidence`; unresolved gaps are explicit `unknown`.
- New diagnostic Event metadata must never contain passwords, decrypted secrets, credentials, or full authenticated RTSP URLs.
- Operations continues to own logs/audit/backup/Prometheus; Playback owns the full browser/codec compatibility matrix.
- No new monitoring service, database, message broker, Prometheus client dependency, or media probing/decoding path is introduced.
- Backend/media behavior changes use TDD; frontend behavior tests assert user-visible behavior and avoid brittle CSS assertions.
- Final verification requires frontend lint/tests/typecheck/build, backend compileall/full pytest, and Docker compose smoke.

---

## File map

### Backend

- Create `backend/app/services/health_realtime.py`: cheap current-state builder shared by REST and websocket.
- Create `backend/app/services/health_reliability.py`: single-query-pass 24h/72h read model and issue synthesis.
- Modify `backend/app/api/health.py`: expose `/api/health/realtime` and `/api/health/reliability`, switch `/ws/status` to realtime payload, preserve compatibility endpoints.
- Modify `backend/app/services/health_monitor.py`: retain compatibility helpers and move reusable pure calculations where needed; do not keep realtime ownership here.
- Modify `backend/app/services/stability_report.py`: delegate shared gap/evidence logic to reliability helpers rather than re-querying nested reports.
- Modify `backend/app/api/recording_management.py`: persist `recording.deleted` evidence before manual deletion removes context.
- Modify `backend/app/main.py`: persist `system.backend_started` after migrations/startup are ready without delaying application startup on notification delivery.
- Test `backend/tests/test_health_realtime_v3.py`.
- Test `backend/tests/test_health_reliability_v3.py`.
- Extend `backend/tests/test_health_gap_diagnostics.py` for evidence precedence.
- Extend recording-management/startup tests for new evidence events.

### Frontend

- Create `frontend/src/stores/healthReliability.ts`: 24h/72h reliability cache, loading/error state, selection and refresh.
- Create `frontend/src/utils/healthDisplay.ts`: status labels/formatters only.
- Create `frontend/src/HealthCenterView.vue`: V3 orchestration and page composition.
- Create `frontend/src/components/health/HealthOverviewStrip.vue`.
- Create `frontend/src/components/health/HealthAttentionList.vue`.
- Create `frontend/src/components/health/CameraReliabilityTable.vue`.
- Create `frontend/src/components/health/CameraHealthDrawer.vue`.
- Create `frontend/src/components/health/HealthServiceStrip.vue`.
- Modify `frontend/src/stores/runtime.ts`: realtime-only types and `/api/health/realtime` fallback; accept `health.realtime` websocket frames.
- Modify `frontend/src/WorkspaceRoute.vue`: render `HealthCenterView` only; stop mounting full compact `PlaybackMetricsPanel` under Health.
- Keep `frontend/src/HealthView.vue` temporarily only if needed as a migration shim; delete it after all Health route tests point to V3.
- Add focused tests for reliability store, Health composition, drawer behavior, and explicit navigation.

---

### Task 1: Cheap realtime health contract

**Files:**
- Create: `backend/app/services/health_realtime.py`
- Modify: `backend/app/api/health.py`
- Modify: `frontend/src/stores/runtime.ts` only after backend contract is green
- Test: `backend/tests/test_health_realtime_v3.py`

**Interfaces:**
- Produces backend `async def realtime_health_snapshot() -> dict[str, Any]`.
- Produces `GET /api/health/realtime`.
- `/ws/status` sends `{ "type": "health.realtime", "data": <same realtime shape> }`.
- Realtime camera rows include `camera_id`, `name`, `ip`, `enabled`, `expected_recording`, `connectivity_status`, `connectivity_source`, `connectivity_failures`, `recorder_state`, `schedule_state`, `abnormal`, restart/error/timestamp guidance fields already needed by Dashboard/shell/Health.
- Realtime top level includes current camera counts, storage state/used percent, upload configured/enabled/active summary, connectivity monitor snapshot and uptime.
- It does **not** include `recordings_24h`, historical completeness, or a Recording aggregation query.

- [ ] **Step 1: Write failing realtime contract tests**

Add tests that monkeypatch historical aggregation paths to raise if touched and call `realtime_health_snapshot()` / websocket builder. Assert current-state fields are present and `recordings_24h` is absent.

```python
@pytest.mark.asyncio
async def test_realtime_health_does_not_load_historical_recording_aggregation(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("historical aggregation must not run on realtime tick")

    monkeypatch.setattr(health_monitor, "health_snapshot", forbidden)
    payload = await realtime_health.realtime_health_snapshot()
    assert "recordings_24h" not in payload
    assert "camera_health" in payload
```

Also assert websocket source references `realtime_health_snapshot`, not `_schedule_aware_snapshot`.

- [ ] **Step 2: Run focused backend test and verify RED**

Run:

```bash
cd backend && uv run python -m pytest tests/test_health_realtime_v3.py -v
```

Expected: FAIL because `health_realtime` / `/api/health/realtime` do not exist and websocket still uses the mixed snapshot.

- [ ] **Step 3: Implement minimal realtime builder**

Build current camera state from `Camera`, `recorder_manager.status()`, connectivity monitor and schedule manager. Read only cheap current storage/upload/system state required by the shell. Do not query `Recording`.

- [ ] **Step 4: Switch health REST/websocket to the realtime builder**

Add `/api/health/realtime`; change `/ws/status` frame type to `health.realtime`. Keep `/api/health/summary` temporarily returning the legacy compatibility snapshot so old frontend code can survive until Task 5.

- [ ] **Step 5: Run focused tests and compileall**

```bash
cd backend && uv run python -m pytest tests/test_health_realtime_v3.py -v
uv run python -m compileall app
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/health_realtime.py backend/app/api/health.py backend/tests/test_health_realtime_v3.py
git commit -m "feat: split realtime health snapshot"
```

---

### Task 2: Unified reliability read model

**Files:**
- Create: `backend/app/services/health_reliability.py`
- Modify: `backend/app/api/health.py`
- Modify: `backend/app/services/stability_report.py`
- Modify: `backend/app/services/health_monitor.py`
- Test: `backend/tests/test_health_reliability_v3.py`
- Test: `backend/tests/test_health_gap_diagnostics.py`

**Interfaces:**
- Produces `async def health_reliability(*, hours: int) -> dict[str, Any]`.
- Produces `GET /api/health/reliability?hours=24|72`.
- Response top level: `generated_at`, `hours`, `criteria`, `overall`, `issues`, `cameras`.
- Each camera uses `recorder_availability_rate`, `recording_completeness`, `recording_gap_count`, `missing_recording_seconds`, `unexplained_recording_gaps`, `outage_count`, `longest_offline_seconds`, `ffmpeg_failures`, `verdict`, `reasons`, `primary_problem`, `diagnostics`.
- Compatibility `health_trends()` and `stability_report()` keep their public shapes but delegate shared pure calculations instead of causing nested historical queries.

- [ ] **Step 1: Write failing reliability contract tests**

Use a small SQLite fixture with cameras, health samples, recordings and events. Assert one response contains both fleet result and diagnostics, uses `recorder_availability_rate`, produces explicit unknown causes, excludes `expected_recording=false` windows, and does not invoke `health_trends()` from the reliability builder.

```python
payload = await health_reliability(hours=24)
assert payload["hours"] == 24
assert "recorder_availability_rate" in payload["overall"]
assert payload["cameras"][0]["diagnostics"][0]["cause"]
assert payload["cameras"][0]["diagnostics"][0]["detail"]
assert payload["cameras"][0]["diagnostics"][0]["confidence"]
```

- [ ] **Step 2: Run focused reliability tests and verify RED**

```bash
cd backend && uv run python -m pytest tests/test_health_reliability_v3.py tests/test_health_gap_diagnostics.py -v
```

Expected: new V3 tests fail because unified builder/contract is absent; existing gap tests remain green.

- [ ] **Step 3: Extract pure reliability helpers and implement one data-load pass**

Within one `SessionLocal` context fetch cameras, bounded samples, overlapping recordings and relevant events exactly once. Reuse/extract pure gap/outage/verdict helpers from `stability_report.py`; do not call `health_trends()` or `stability_report()` from `health_reliability()`.

- [ ] **Step 4: Synthesize issue summaries**

Build `issues[]` from failed/collecting current reliability rows and service-independent camera diagnostics. Each issue has `kind`, `severity`, `camera_id`, `title`, `detail`, `started_at`/`ended_at` when applicable, `cause`, `confidence`, and a deterministic `action` descriptor such as `camera`, `events`, `playback`, or `operations`.

- [ ] **Step 5: Add API endpoint and compatibility delegation**

Add `/api/health/reliability`. Keep `/trends` and `/stability` response fields used by old tests, but route their calculations through shared helpers/read-model data rather than nested high-level queries.

- [ ] **Step 6: Run focused backend tests**

```bash
cd backend && uv run python -m pytest tests/test_health_reliability_v3.py tests/test_health_gap_diagnostics.py tests/test_health_status.py tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/health_reliability.py backend/app/services/stability_report.py backend/app/services/health_monitor.py backend/app/api/health.py backend/tests/test_health_reliability_v3.py backend/tests/test_health_gap_diagnostics.py
git commit -m "feat: add unified health reliability model"
```

---

### Task 3: Persist manual deletion and backend-start evidence

**Files:**
- Modify: `backend/app/api/recording_management.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/health_reliability.py`
- Test: extend `backend/tests/test_recording_management_delete.py`
- Test: extend/create `backend/tests/test_health_evidence_v3.py`

**Interfaces:**
- Manual deletion writes Event `category="recording"`, `code="recording.deleted"`, with `camera_id`, prior recording id, start/end interval, local/cloud availability flags and `reason="manual"` before the Recording row is deleted.
- Backend startup writes Event `category="system"`, `code="system.backend_started"`, timestamp/build-safe metadata only.
- Gap cause priority: manual deletion > segment processing failure > camera outage > FFmpeg failure > backend restart > recorder unavailable > unknown.

- [ ] **Step 1: Write failing evidence tests**

Assert manual deletion persists an Event even when the Recording row is removed. Assert reliability maps an overlapping `recording.deleted` event to `manual_deletion` with high confidence. Assert a bounded overlapping `system.backend_started` may produce `backend_restart` with medium confidence, but a distant start event does not.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
cd backend && uv run python -m pytest tests/test_recording_management_delete.py tests/test_health_evidence_v3.py -v
```

- [ ] **Step 3: Implement evidence persistence**

Persist deletion evidence before `db.delete(recording)`. Add backend-start Event during application lifespan after DB migration/startup initialization; do not include secrets or block startup on external notification work.

- [ ] **Step 4: Extend deterministic cause correlation**

Add `manual_deletion` and `backend_restart` labels and precedence to the reliability helper. Require actual temporal overlap/bounded matching before assigning a cause.

- [ ] **Step 5: Run focused tests**

```bash
cd backend && uv run python -m pytest tests/test_recording_management_delete.py tests/test_health_evidence_v3.py tests/test_health_gap_diagnostics.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/recording_management.py backend/app/main.py backend/app/services/health_reliability.py backend/tests/test_recording_management_delete.py backend/tests/test_health_evidence_v3.py
git commit -m "feat: persist health diagnostic evidence"
```

---

### Task 4: Frontend realtime/reliability stores

**Files:**
- Modify: `frontend/src/stores/runtime.ts`
- Create: `frontend/src/stores/healthReliability.ts`
- Create: `frontend/src/stores/healthReliability.test.ts`
- Create: `frontend/src/utils/healthDisplay.ts`

**Interfaces:**
- Runtime store consumes `/api/health/realtime` and `health.realtime` websocket frames only for health state.
- Reliability store exposes `windowHours`, `report`, `loading`, `error`, `lastLoadedAt`, `setWindow(hours)`, `refresh(force?)`, and caches 24/72 results separately.
- `setWindow` accepts only `24 | 72`.

- [ ] **Step 1: Write failing store behavior tests**

Test that 24h loads `/api/health/reliability?hours=24`, switching to 72h loads once, switching back reuses cache until forced refresh, and reliability failure does not clear realtime runtime state.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd frontend && npm test -- healthReliability.test.ts
```

- [ ] **Step 3: Implement reliability store and display helpers**

Use axios and Pinia. Keep formatting/labels out of the store.

- [ ] **Step 4: Migrate runtime store contract**

Rename the mixed snapshot type to a realtime-specific shape; `refreshHealth()` calls `/api/health/realtime`; websocket accepts `health.realtime`. Preserve Dashboard/shell-required fields by adapting their type access, not by restoring historical data to realtime.

- [ ] **Step 5: Run store plus existing runtime/dashboard tests**

```bash
cd frontend && npm test -- healthReliability.test.ts
npm test
```

Do not claim completion if unrelated regression tests fail; fix consumers before proceeding.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/runtime.ts frontend/src/stores/healthReliability.ts frontend/src/stores/healthReliability.test.ts frontend/src/utils/healthDisplay.ts
git commit -m "feat: split health realtime and reliability state"
```

---

### Task 5: Health Center V3 page composition

**Files:**
- Create: `frontend/src/HealthCenterView.vue`
- Create: `frontend/src/components/health/HealthOverviewStrip.vue`
- Create: `frontend/src/components/health/HealthAttentionList.vue`
- Create: `frontend/src/components/health/CameraReliabilityTable.vue`
- Create: `frontend/src/components/health/CameraHealthDrawer.vue`
- Create: `frontend/src/components/health/HealthServiceStrip.vue`
- Modify: `frontend/src/WorkspaceRoute.vue`
- Delete after migration: `frontend/src/HealthView.vue`
- Test: create `frontend/src/healthCenterV3.test.ts`

**Interfaces:**
- Main ordering: overview/header controls → `需要关注` → reliability table → service strip; drawer is overlay detail.
- Drawer opens by row click and never starts media automatically.
- Explicit Playback action routes with camera/date/wall-clock context but does not synthesize autoplay unless it is an already-supported explicit user action.
- Operations action goes to `/settings?section=operations`; camera action goes to `/cameras?camera_id=<id>`; Event action goes to `/events` with supported query context only.

- [ ] **Step 1: Write failing visible-behavior tests**

Using component/source tests consistent with repository conventions, assert:

```text
需要关注 appears before 摄像头可靠性
24h and 72h controls exist
row selection opens diagnostic drawer
cause/detail/confidence are rendered in drawer
historical-error empty state leaves realtime area present
WorkspaceRoute renders HealthCenterView and no longer mounts PlaybackMetricsPanel compact
```

- [ ] **Step 2: Run focused frontend tests and verify RED**

```bash
cd frontend && npm test -- healthCenterV3.test.ts
```

- [ ] **Step 3: Implement the five focused components**

Keep the main table concise. Do not render concatenated full gap diagnostics in table cells. `HealthAttentionList` prioritizes active realtime problems, then selected-window failed reliability issues.

- [ ] **Step 4: Implement diagnostic drawer actions**

Render current state, selected-window reliability, diagnostic timeline and explicit navigation buttons. For recording-gap Playback action calculate date/wall seconds from diagnostic start and route to Playback without auto media on drawer open.

- [ ] **Step 5: Replace Health route composition**

Update `WorkspaceRoute.vue` to lazy-load/render `HealthCenterView` only for health. Remove compact `PlaybackMetricsPanel` from the Health route. Delete old `HealthView.vue` after references/tests are migrated.

- [ ] **Step 6: Run focused and full frontend tests**

```bash
cd frontend && npm test -- healthCenterV3.test.ts healthReliability.test.ts
npm run lint
npm test
npm run build
```

Expected: 0 lint errors, all tests pass, `vue-tsc --noEmit && vite build` succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/HealthCenterView.vue frontend/src/components/health frontend/src/WorkspaceRoute.vue frontend/src/healthCenterV3.test.ts frontend/src/stores frontend/src/utils/healthDisplay.ts
git rm frontend/src/HealthView.vue
git commit -m "feat: rebuild Health Center V3"
```

---

### Task 6: Compact service health without cross-workspace duplication

**Files:**
- Modify: `frontend/src/components/health/HealthServiceStrip.vue`
- Create/extend: `frontend/src/components/health/HealthServiceStrip.test.ts`
- Reuse: existing `/api/playback/metrics`; no backend websocket/reliability changes for playback metrics.

**Interfaces:**
- Realtime contract supplies storage/upload/FFmpeg/connectivity-monitor summary.
- Health page fetches `/api/playback/metrics` only while mounted, at ~60s cadence, and derives only startup success/P95/problem count summary.
- Service cards link to destination workspaces; they do not embed full Operations or browser-compatibility tables.

- [ ] **Step 1: Write failing service-strip tests**

Assert it requests `/api/playback/metrics`, renders only compact fields, links detailed playback diagnostics to the recordings/playback compatibility destination, and contains no full compatibility table markup.

- [ ] **Step 2: Run focused test and verify RED**

```bash
cd frontend && npm test -- HealthServiceStrip.test.ts
```

- [ ] **Step 3: Implement compact service summary**

Use component-local loading/timer lifecycle. Do not add playback metrics to runtime websocket or reliability store.

- [ ] **Step 4: Run frontend tests/build**

```bash
cd frontend && npm run lint && npm test && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/health/HealthServiceStrip.vue frontend/src/components/health/HealthServiceStrip.test.ts
git commit -m "feat: add compact Health service diagnostics"
```

---

### Task 7: Compatibility, performance regression and final verification

**Files:**
- Modify tests only unless a discovered regression requires production correction.
- Update `docs/superpowers/specs/2026-09-15-health-center-v3-design.md` status to Implemented only after all verification passes.
- Optionally update `docs/V1_STATUS.md` only if wording materially changes; do not claim external 24h/72h acceptance is complete.

**Interfaces:**
- Old `/api/health/summary`, `/trends`, `/stability` remain compatible enough for existing callers/tests during V3 rollout.
- Global shell and Dashboard consume realtime fields without historical aggregation.

- [ ] **Step 1: Add/confirm performance-contract regression tests**

Assert `/ws/status` calls only realtime builder; reliability builder does not call `health_trends()`/`stability_report()`; compatibility endpoints preserve critical fields expected by existing tests.

- [ ] **Step 2: Run full backend verification**

```bash
cd backend
uv run python -m compileall app
uv run python -m pytest
```

Expected: 0 failed.

- [ ] **Step 3: Run full frontend verification**

```bash
cd frontend
npm run lint
npm test
npm run build
```

Expected: 0 lint errors; existing baseline warnings may remain only if unchanged; all tests pass; typecheck/build pass.

- [ ] **Step 4: Run Docker compose smoke through repository CI/deployment workflow**

Verify compose config, backend/frontend image build, startup, backend health, frontend proxy health and upload websocket proxy.

- [ ] **Step 5: Review final diff against the spec**

Checklist:

```text
[ ] problem-first Health page
[ ] realtime/historical split
[ ] one reliability request path
[ ] diagnostic drawer with evidence/confidence
[ ] manual deletion + backend start evidence
[ ] Operations/Playback details not duplicated
[ ] manual media-start semantics preserved
[ ] no secrets in evidence
[ ] old health routes compatibility retained
[ ] no claim that external 24h/72h field acceptance is complete
```

- [ ] **Step 6: Update design status only after verification**

Change design `Status: Proposed design` to `Status: Implemented` and record the implementation PR/CI references.

- [ ] **Step 7: Final commit**

```bash
git add docs backend frontend
git commit -m "docs: record Health Center V3 verification"
```
