# Health Center V3 Design

Date: 2026-09-15
Status: Proposed design
Scope: Camera Recorder system health information architecture, read models, diagnostics, and frontend composition

## 1. Problem statement

The current System Health page has grown from a small operational summary into a mixed dashboard containing:

- realtime camera connectivity / recorder / schedule state;
- 24h recording statistics;
- historical reliability trends;
- 24h / 72h stability acceptance;
- recording gap diagnostics;
- storage protection state;
- upload state;
- playback/browser health.

Several concepts are also presented elsewhere:

- Dashboard already answers “what needs attention now?”;
- Operations shows recorder/process, connectivity monitor, storage, logs, audit, backup and metrics;
- Playback contains detailed browser / codec playback compatibility data;
- System Health independently repeats parts of each area.

The backend data path is also unnecessarily expensive. The global runtime store keeps `/ws/status` open for the whole application. The websocket currently rebuilds `_schedule_aware_snapshot()` roughly every two seconds, and that path includes SQLite 24h Recording aggregation, UploadTask aggregation and storage state. Health then separately requests `/api/health/trends` and `/api/health/stability`, while the stability report also depends on trend-like data.

Health Center V3 should remove this duplication and make the page diagnostic rather than encyclopedic.

## 2. Product goal

System Health should answer, in this order:

1. **What is wrong now?**
2. **What reliability problem happened during the selected period?**
3. **Why did it happen, and how confident are we?**
4. **Where should the operator go to fix or investigate it?**

The page is not a second Dashboard, a second Operations page, or a second Playback metrics page.

Primary mental model:

> status → problem → evidence → action

## 3. Non-goals

Health Center V3 will not:

- create a second event database;
- introduce Prometheus/Grafana/ELK services;
- implement incident acknowledgement / assignment / SLA workflows;
- change media startup semantics;
- change recording policy or segment duration;
- auto-start camera preview or playback;
- replace Event Center;
- duplicate full Operations logs, backup/restore or audit UIs;
- duplicate the full browser/codec compatibility matrix from Playback.

A future Incident Center may build on the evidence model, but is explicitly out of scope.

## 4. Design principles

### 4.1 Problem-first, not metric-first

Healthy systems should be visually quiet. The first large content section is “Needs Attention”, not a wall of green counters.

### 4.2 Realtime and historical reliability are separate data products

Realtime state should be cheap and frequent. Historical reliability may query SQLite and perform correlation, but refreshes much less frequently and only while Health is open or explicitly refreshed.

### 4.3 One health row per camera

The current 24h Reliability table and Stability Acceptance table describe the same fleet from different angles. They become one Camera Reliability Matrix.

### 4.4 Details belong in a diagnostic drawer

The main table exposes a small operator-relevant set of columns. Gap intervals, event evidence, confidence, timestamps and guidance belong in a right-side diagnostic drawer.

### 4.5 Evidence is persisted at the failure boundary

When a component knows why data was lost, it persists structured evidence before context disappears. Health correlation must not invent a specific cause when no evidence exists.

## 5. Target page information architecture

### 5.1 Header

Compact header controls:

- realtime feed state: connected / fallback polling;
- selected reliability window: 24h / 72h;
- refresh button;
- last reliability refresh timestamp.

No extra page-title block is required because the global shell already owns the title.

### 5.2 Overall health strip

A restrained five-item strip:

- cameras needing attention now;
- monitored cameras passing the selected reliability window;
- recording gaps and total missing duration;
- longest outage;
- storage state.

Do not repeat counters already visible in the global status bar unless they directly support diagnosis.

### 5.3 Needs Attention

This is the first major section.

Each issue card contains:

- severity;
- camera/service name;
- concise problem statement;
- time or interval;
- most likely cause;
- confidence when historical diagnosis is involved;
- one primary action.

Examples:

- `Front Door · missing 4m 58s recording · segment probe failed · high confidence`
- `Garage · offline for 2m 13s · RTSP connectivity lost`
- `Storage · critical threshold reached · cleanup protection active`
- `Playback · Safari HEVC startup success below threshold · open Playback diagnostics`

Healthy state shows one quiet “No issues detected” state instead of green cards for every subsystem.

### 5.4 Camera Reliability Matrix

One row per monitored camera.

Visible columns:

- Camera
- Now: connectivity + recorder state
- Recorder availability
- Recording completeness
- Recording gaps
- Missing duration
- Outages
- Primary cause
- Result: pass / fail / collecting

Clicking a row opens the diagnostic drawer. Camera configuration navigation is an explicit drawer action.

The main table must not contain long concatenated diagnostic strings.

### 5.5 Diagnostic drawer

The drawer has four blocks.

#### Current state

- connectivity state/source/failure streak;
- recorder state/restarts/current offline duration;
- schedule / expected-recording state;
- timestamp mode and guidance.

#### Reliability summary

For the selected 24h or 72h period:

- recorder availability;
- recording completeness;
- gap count and missing duration;
- outage count and longest outage;
- FFmpeg failure count.

#### Diagnosed problem timeline

- recording gaps;
- connectivity outages;
- FFmpeg failures;
- segment-processing failures;
- manual deletion evidence;
- backend restart evidence when relevant.

Every diagnostic item contains cause, detail and confidence. Unknown remains explicit.

#### Actions

- open camera settings;
- open Event Center at relevant evidence when a deep link exists;
- open Playback at relevant wall-clock time for a recording gap;
- open Operations for logs and low-level investigation.

Actions remain explicit and therefore preserve the manual-media-start contract. Merely opening Health or the drawer never starts media.

### 5.6 Service health strip

A compact service strip, not full operational panels:

- storage;
- upload/archive;
- FFmpeg capabilities;
- connectivity monitor;
- playback/browser health.

Data ownership is explicit:

- storage/upload/FFmpeg/connectivity-monitor current state comes from the lightweight realtime/system state;
- playback health uses the existing `/api/playback/metrics` endpoint at Health-page cadence only;
- playback metrics are **not** added to `/ws/status` and are **not** embedded in `/api/health/reliability`.

Each item shows state + one useful summary + destination. Detailed logs/config/metrics stay in Operations. Detailed browser compatibility stays in Playback.

## 6. Backend data architecture

### 6.1 Lightweight realtime snapshot

Introduce a realtime health read model whose only job is current state.

User-facing API contract:

- `GET /api/health/realtime`
- `/ws/status` emits `{ "type": "health.realtime", "data": ... }`

Payload contains:

- `generated_at`;
- process uptime;
- camera current connectivity / recorder / schedule / abnormal state;
- current storage threshold state and used percent;
- current upload enabled/configured/active summary and current queue/error counters only if available without 24h aggregation;
- current FFmpeg capability state;
- current connectivity monitor state.

It must not perform 24h Recording aggregation on every websocket tick.

The realtime builder may read camera configuration/state from SQLite when required, but it must not scan or aggregate historical Recording rows, historical HealthSample rows, or historical Event rows.

Compatibility plan:

- keep `/api/health/summary` temporarily as an adapter for existing consumers;
- runtime store migrates to a new `RealtimeHealthSnapshot` type;
- after all first-party consumers switch, `/ws/status` carries only `health.realtime` and no historical 24h fields.

### 6.2 Unified reliability read model

Add one historical endpoint:

`GET /api/health/reliability?hours=24|72`

It replaces the Health Center frontend need to fetch both `trends` and `stability`.

Top-level response:

```text
generated_at
hours
criteria
overall
issues[]
cameras[]
```

`overall` contains:

- monitored_cameras;
- passed / failed / collecting counts;
- recorder_availability_rate;
- recording_completeness;
- recording_gap_count;
- missing_recording_seconds;
- unexplained_recording_gaps;
- outage_count;
- longest_outage_seconds;
- ffmpeg_failures.

Each camera contains identifiers, reliability fields, a compact `primary_problem`, and the already-computed diagnostic rows needed by the drawer. V3 does not introduce a second per-camera reliability endpoint because that would repeat correlation work.

Service state and playback metrics are not part of this response.

### 6.3 Avoid duplicate computation

The reliability builder owns one logical data-load/correlation pass per request:

1. fetch cameras;
2. fetch health samples for selected period;
3. fetch recordings overlapping the selected period;
4. fetch relevant structured events;
5. derive availability, completeness, outages and gaps;
6. correlate causes once;
7. produce overall + camera rows + issue summaries.

`stability_report()` and `health_trends()` may remain compatibility wrappers initially, but they must delegate to shared pure calculations/read-model primitives rather than independently re-querying the same period.

No high-level report endpoint may call another high-level report function that repeats database loads.

### 6.4 Naming correction

The old `online_rate` in health trends actually means “Recorder was available when recording was expected”, not camera network reachability.

The V3 contract names it:

`recorder_availability_rate`

Compatibility wrappers may continue returning `online_rate` until old consumers are removed.

## 7. Diagnostic evidence model

Health correlation remains evidence-based. Cause priority is deterministic:

1. explicit manual recording deletion;
2. segment processing failure;
3. camera connectivity outage;
4. FFmpeg start/exit/failure streak;
5. backend restart overlapping expected recording;
6. Recorder unhealthy samples;
7. unknown.

Higher-priority evidence wins only when its timestamp/interval overlaps the gap or falls within the existing bounded correlation window.

### 7.1 New evidence events

Add structured events where context is currently lost.

#### `recording.deleted`

Persist before deleting the Recording row:

- `camera_id`;
- prior recording id in metadata, not as an Event foreign key to the soon-deleted row;
- recording start/end;
- local/cloud availability state;
- `reason="manual"`.

The event must survive deletion of the Recording row.

#### `system.backend_started`

Persist once during backend application startup after database initialization/migration succeeds:

- startup timestamp;
- build/version/commit identifier when available without inventing one.

A backend-start event does not automatically blame every nearby gap. It becomes a medium-confidence cause only when the restart overlaps an expected-recording interval and surrounding evidence makes it plausible.

Existing evidence remains:

- `recording.segment_processing_failed`;
- `camera.connection_lost` / `camera.connection_restored`;
- `camera.ffmpeg_start_failed`;
- `camera.ffmpeg_exited`;
- `camera.ffmpeg_failure_streak`.

No secrets, RTSP credentials or decrypted passwords may appear in evidence metadata.

## 8. Frontend component boundaries

Replace the monolithic HealthView responsibility with focused units:

```text
HealthCenterView.vue
  HealthOverviewStrip.vue
  HealthAttentionList.vue
  CameraReliabilityTable.vue
  CameraHealthDrawer.vue
  HealthServiceStrip.vue
```

Shared state / display logic:

```text
stores/runtime.ts                 realtime only
stores/healthReliability.ts       historical 24h/72h report + selection/cache
utils/healthDisplay.ts            labels/formatting only
```

`HealthCenterView.vue` orchestrates loading, time-window selection and drawer selection; it does not own large rendering rules.

The reliability store caches the most recent 24h and 72h responses separately. A cache entry is considered fresh for 60 seconds. Switching back to a fresh window does not immediately re-request it; explicit Refresh always bypasses the cache.

Refresh behavior:

- realtime: websocket roughly every 2 seconds using the cheap realtime builder;
- realtime fallback: existing REST fallback cadence when socket is disconnected;
- reliability: load on Health entry, then refresh every 60 seconds while Health remains visible;
- playback health summary: call existing `/api/playback/metrics` on Health entry and every 60 seconds while visible;
- leaving Health stops reliability/playback polling but does not stop the global realtime runtime store.

## 9. Relationship to other workspaces

### Dashboard

Dashboard remains “what should I pay attention to right now?” at a high level. It may link into Health with camera context but does not show 24h/72h diagnostics.

### Event Center

Event Center remains the chronological event stream. Health uses events as evidence but does not replace event browsing.

### Operations

Operations owns logs, audit, backup/restore and Prometheus. Health links there for low-level investigation.

### Playback

Playback owns the full browser/codec/startup compatibility matrix. Health only renders a compact health summary sourced from the existing playback metrics API and links to Playback for details.

### Cameras

Cameras owns device configuration. Health can deep-link to a specific camera but does not duplicate its configuration drawer.

## 10. Error and empty-state behavior

Realtime and historical data fail independently.

- If websocket fails, retain the last realtime snapshot and show fallback-polling state.
- If reliability request fails, realtime health remains usable and the reliability section shows unavailable + Retry.
- If playback metrics fail, only the playback service item shows unavailable; camera reliability remains usable.
- If there are insufficient samples, show `collecting`, never `pass`.
- If a recording gap has no evidence, show `unknown` with low confidence, never omit cause/detail/confidence.
- If there are no issues, show one quiet “No issues detected in selected period” state.
- Historical structured evidence only exists after the corresponding version was deployed; V3 must not fabricate causes for older gaps.

## 11. Performance constraints

The refactor is successful only if it reduces background work.

Required properties:

- `/ws/status` does not execute 24h Recording aggregation per tick;
- `/ws/status` does not load historical HealthSample/Event datasets;
- reliability queries occur only while Health is open or explicitly refreshed;
- one reliability request does not query the same dataset twice through nested report calls;
- 24h/72h switching uses the 60-second frontend cache described above;
- playback health is polled at Health-page cadence, not websocket cadence;
- queries remain bounded by selected period and camera set;
- no media probing/decoding is introduced into health reporting.

## 12. API migration strategy

### Phase A — backend read models and evidence

- add the realtime builder and `/api/health/realtime`;
- make `/ws/status` publish the realtime builder result;
- add shared reliability builder and `/api/health/reliability`;
- add `recording.deleted` and `system.backend_started` evidence;
- preserve `/summary`, `/trends`, `/stability` through compatibility adapters;
- add backend tests proving historical aggregation is absent from realtime.

### Phase B — frontend migration

- migrate runtime store to realtime contract;
- add `healthReliability` store;
- replace current Health page with V3 component structure;
- remove the mounted `PlaybackMetricsPanel compact` from `WorkspaceRoute` Health composition;
- render playback service summary inside `HealthServiceStrip` using the existing playback metrics endpoint;
- verify Dashboard/shell/Cameras consumers still receive all current-state fields they use.

### Phase C — internal cleanup

- remove duplicate historical computation paths;
- old public endpoints may remain as cheap compatibility wrappers, but do not maintain separate business rules;
- delete obsolete HealthView-only types and formatting after consumers migrate.

The route remains `/health-center`.

## 13. Testing strategy

### Backend TDD

Required regression / contract tests:

- realtime builder does not call historical Recording aggregation helpers;
- realtime builder does not load HealthSample/Event history;
- websocket uses realtime builder, not historical report builder;
- reliability builder loads each logical dataset once per request;
- planned non-recording windows are excluded from gaps;
- `recording.deleted` is persisted before row deletion and correlates to manual-deletion cause;
- `system.backend_started` correlation requires temporal overlap and never globally blames gaps;
- segment-processing failure / outage / FFmpeg / restart / recorder-unavailable precedence is deterministic;
- every counted gap has cause/detail/confidence;
- insufficient history returns collecting rather than false pass;
- compatibility wrappers preserve critical existing fields during migration.

### Frontend behavior tests

Test visible behavior rather than brittle CSS selectors:

- Needs Attention appears before the fleet table;
- healthy selected period shows the quiet empty state;
- 24h / 72h selection requests the correct reliability window and respects the 60-second cache;
- explicit Refresh bypasses the cache;
- camera row opens diagnostic drawer;
- drawer renders gap interval, cause, detail and confidence;
- actions route to Cameras / Events / Playback / Operations without automatic media startup;
- historical request failure does not hide realtime state;
- playback metrics failure only degrades the playback service item;
- full Playback compatibility table is no longer embedded in Health.

### Verification

Final implementation PR must pass:

- frontend lint;
- frontend tests;
- `vue-tsc --noEmit`;
- Vite production build;
- backend compileall;
- full pytest;
- Docker compose smoke.

## 14. Rollout and backward compatibility

No database migration is required for the page restructuring or new evidence events because they reuse the existing Event table.

After deployment:

- new segment/deletion/startup evidence improves diagnosis going forward;
- old gaps without historical evidence may remain unknown;
- `/health-center` deep links continue to work;
- `/api/health/summary`, `/trends`, and `/stability` remain temporarily available through adapters;
- manual media-start behavior is unchanged.

## 15. Success criteria

Health Center V3 is complete when:

- an operator can identify the current problem and likely cause without scanning multiple large tables;
- missing recording intervals show a persisted/correlated cause when evidence exists and explicit unknown when it does not;
- the realtime websocket path no longer performs historical 24h aggregation every tick;
- Health uses one historical reliability read model instead of separately composing trends + stability in the browser;
- duplicated Operations and Playback detail is removed from Health;
- the frontend is split into focused units instead of one monolithic HealthView;
- Dashboard, Event Center, Cameras, Playback and Operations responsibilities remain intact;
- final CI verification is green;
- the manual-media-start contract remains preserved.
