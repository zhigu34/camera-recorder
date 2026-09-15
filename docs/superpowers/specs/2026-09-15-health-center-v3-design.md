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

Several of those concepts are also presented elsewhere:

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

A future Incident Center may build on the evidence model, but is explicitly out of this scope.

## 4. Design principles

### 4.1 Problem-first, not metric-first

Healthy systems should be visually quiet. The first large section is “Needs Attention”, not a wall of green counters.

### 4.2 Realtime and historical reliability are separate data products

Realtime state should be cheap and frequent. Historical reliability may query SQLite and perform correlation, but should refresh much less frequently and only when requested by the page.

### 4.3 One health row per camera

The current 24h Reliability table and Stability Acceptance table describe the same fleet from different angles. They will be merged into one camera reliability matrix.

### 4.4 Details belong in a diagnostic drawer

The main table should expose a small set of operator-relevant columns. Gap intervals, event evidence, confidence, timestamps and guidance belong in a right-side diagnostic drawer.

### 4.5 Evidence is persisted at the failure boundary

When a system component knows why data was lost, it must persist structured evidence before context disappears. Health correlation should not infer a specific cause when no evidence exists.

## 5. Target page information architecture

### 5.1 Header

Compact page header:

- realtime feed state: connected / fallback polling;
- selected reliability window: 24h / 72h;
- refresh button;
- generated-at / last historical refresh timestamp.

No separate page title block is necessary because the global shell already owns the title.

### 5.2 Overall health strip

A restrained five-item strip:

- cameras needing attention now;
- monitored cameras passing the selected reliability window;
- recording gaps and total missing duration;
- longest outage;
- storage state.

Do not show counters that are available in the global status bar unless they contribute directly to diagnosis.

### 5.3 Needs Attention

This is the first content section.

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

Healthy state shows a single quiet empty state instead of green cards for every subsystem.

### 5.4 Camera Reliability Matrix

One row per monitored camera.

Recommended visible columns:

- Camera
- Now: connectivity + recorder state
- Availability: renamed from historical `online_rate` to `recorder_availability_rate`
- Recording completeness
- Recording gaps
- Missing duration
- Outages
- Last / primary cause
- Result: pass / fail / collecting

Clicking a row opens the diagnostic drawer. Clicking the camera identity may still deep-link to `/cameras?camera_id=<id>` through an explicit action in the drawer.

The main table must not contain long concatenated diagnostic strings.

### 5.5 Diagnostic drawer

The drawer has four blocks:

1. **Current state**
   - connectivity state/source/failure streak;
   - recorder state/restarts/current offline duration;
   - schedule / expected-recording state;
   - timestamp mode and guidance.

2. **Reliability summary for selected period**
   - recorder availability;
   - recording completeness;
   - gap count and missing duration;
   - outage count and longest outage;
   - FFmpeg failure count.

3. **Timeline of diagnosed problems**
   - gaps;
   - connectivity outages;
   - FFmpeg failures;
   - segment-processing failures;
   - manual deletion evidence;
   - service restart evidence where relevant.

   Every diagnostic row contains cause, detail and confidence. Unknown remains explicit.

4. **Actions**
   - open camera settings;
   - open Event Center filtered/deep-linked when possible;
   - open Playback at a relevant wall-clock time when the issue is a recording gap;
   - open Operations logs for low-level investigation.

Actions remain explicit and therefore preserve the manual-media-start contract.

### 5.6 Service health footer

A compact service strip, not full operational panels:

- storage;
- upload/archive;
- FFmpeg capabilities;
- connectivity monitor;
- playback/browser health.

Each item shows only state + one useful summary + destination. Detailed logs/config/metrics stay in Operations. Detailed browser compatibility stays in Playback.

## 6. Backend data architecture

### 6.1 Lightweight realtime snapshot

Introduce a realtime health read model whose job is only current state.

Suggested endpoint / socket payload:

- `GET /api/health/realtime`
- `/ws/status` emits the same `health.realtime` payload

Payload contains:

- generated_at;
- uptime if cheap;
- camera current connectivity / recorder / schedule / abnormal state;
- current storage threshold state and used percent;
- current upload active/configured/failure summary only if obtainable without 24h aggregation;
- current connectivity monitor state.

It must not perform 24h Recording aggregation on every websocket tick.

Compatibility plan:

- keep `/api/health/summary` temporarily as a compatibility alias or adapter while frontend migration is in progress;
- after all consumers switch, remove the expensive historical fields from the websocket contract;
- runtime store types should reflect the new realtime contract rather than the old mixed `HealthSnapshot`.

### 6.2 Unified reliability read model

Add a single historical endpoint:

`GET /api/health/reliability?hours=24|72`

It replaces the frontend need to fetch both `trends` and `stability` for the Health Center.

Top-level response:

```text
generated_at
hours
criteria
overall
issues[]
cameras[]
service_health
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

Each camera contains current identifiers plus the reliability fields and a compact `primary_problem` summary. Full diagnostics may either be embedded or fetched by camera from the same computed report; V1 implementation should prefer embedding the already-computed diagnostic rows to avoid duplicate work.

### 6.3 Avoid duplicate computation

The reliability builder owns one query/correlation pass per request:

1. fetch cameras;
2. fetch health samples for selected period;
3. fetch recordings overlapping the period;
4. fetch relevant structured events;
5. derive availability, completeness, outages and gaps;
6. correlate causes once;
7. return overall + camera rows + issue summaries.

`stability_report()` and `health_trends()` may remain compatibility wrappers initially, but they should delegate to shared pure helpers/read-model builders rather than independently repeating DB work.

No endpoint should call another high-level report function that re-queries the same period.

### 6.4 Naming correction

The old `online_rate` in health trends means “Recorder was available when recording was expected”, not physical camera network availability.

The V3 contract should name it:

`recorder_availability_rate`

Compatibility wrappers may continue returning `online_rate` until old consumers are removed.

## 7. Diagnostic evidence model

Health correlation remains evidence-based. Cause priority should be deterministic and documented.

Recommended priority:

1. explicit manual recording deletion;
2. segment processing failure;
3. camera connectivity outage;
4. FFmpeg start/exit/failure streak;
5. backend/system restart overlapping expected recording;
6. Recorder unhealthy samples;
7. unknown.

Higher-priority evidence wins only when its timestamp/interval actually overlaps or is within the bounded correlation window.

### 7.1 New evidence events

Add structured events where context is currently lost:

- `recording.deleted`
  - camera_id;
  - recording start/end;
  - recording id or prior id;
  - local/cloud state;
  - reason=`manual`.

- `system.backend_started`
  - startup timestamp;
  - build/version when available.

A process start event should not automatically blame every nearby gap. It is evidence with medium confidence only when expected-recording samples or surrounding intervals indicate the restart plausibly caused the gap.

Existing evidence remains:

- `recording.segment_processing_failed`;
- `camera.connection_lost` / `camera.connection_restored`;
- `camera.ffmpeg_start_failed`;
- `camera.ffmpeg_exited`;
- `camera.ffmpeg_failure_streak`.

No secrets, RTSP credentials or decrypted passwords may appear in evidence metadata.

## 8. Frontend component boundaries

Replace the monolithic HealthView responsibility with focused components. Suggested structure:

```text
HealthCenterView.vue
  HealthOverviewStrip.vue
  HealthAttentionList.vue
  CameraReliabilityTable.vue
  CameraHealthDrawer.vue
  HealthServiceStrip.vue
```

Shared data/composition logic:

```text
stores/runtime.ts                 realtime only
stores/healthReliability.ts       historical 24h/72h report + selection
utils/healthDisplay.ts            labels/formatting only
```

`HealthCenterView.vue` orchestrates loading and selection but does not own large rendering rules.

The reliability store should cache the most recent 24h and 72h responses independently and refresh on demand / page interval. It should not poll every two seconds.

Suggested refresh behavior:

- realtime: websocket ~2s as today, but cheap payload;
- reliability: load on entry, refresh every 60s while visible, immediate refresh after user action;
- playback compact health: its existing own cadence, but Health only consumes a compact summary rather than mounting a full metrics panel if a lightweight summary endpoint/read is available.

## 9. Relationship to other workspaces

### Dashboard

Dashboard keeps “what should I pay attention to right now?” at a high level. It may link into Health with a camera/query target but does not show 24h/72h diagnostics.

### Event Center

Event Center is the chronological event stream. Health uses events as evidence but does not replace event browsing.

### Operations

Operations owns logs, audit, backup/restore and Prometheus. Health links there for deep investigation.

### Playback

Playback owns full browser/codec/startup compatibility. Health shows only an unhealthy/healthy summary and a link.

### Cameras

Cameras owns device configuration. Health can deep-link to a specific camera but must not duplicate its configuration drawer.

## 10. Error and empty-state behavior

Realtime and historical data fail independently.

- If websocket fails, retain last realtime snapshot and show fallback-polling state.
- If reliability request fails, keep realtime health usable and show the historical section as unavailable with retry.
- If there are insufficient samples, show `collecting`, never `pass`.
- If a recording gap has no evidence, show `Unknown cause` with low confidence, never omit the field.
- If there are no issues, show one quiet “No issues detected in selected period” state.
- Historical structured evidence only exists after the corresponding version was deployed; V3 must not fabricate causes for older gaps.

## 11. Performance constraints

The refactor is successful only if it also reduces background work.

Required properties:

- `/ws/status` does not execute 24h Recording aggregation per tick;
- reliability queries occur only while Health is open or explicitly refreshed;
- a single reliability request does not query the same dataset twice through nested report calls;
- 24h/72h switching may use short frontend caching to avoid duplicate immediate requests;
- queries remain bounded by period and camera set;
- no media probing/decoding is introduced into health reporting.

## 12. API migration strategy

Phase A:

- create shared reliability builder and new `/api/health/reliability`;
- create realtime builder and new realtime contract;
- preserve old `/summary`, `/trends`, `/stability` behavior through adapters where practical;
- add tests comparing critical compatibility fields.

Phase B:

- migrate runtime store and Health Center frontend to new APIs;
- stop mounting the full `PlaybackMetricsPanel compact` under Health;
- verify Dashboard/shell/Cameras consumers still receive required realtime fields.

Phase C:

- remove duplicated internal query paths;
- old public endpoints can remain for compatibility if cheap wrappers, but should not maintain separate business logic.

This design does not require a breaking route change: `/health-center` remains the user-facing URL.

## 13. Testing strategy

### Backend TDD

Required regression / contract tests:

- realtime snapshot excludes historical Recording aggregation path;
- websocket uses realtime builder, not the historical report builder;
- reliability builder performs one logical data load per dataset for a request;
- planned non-recording windows are excluded from gaps;
- `recording.deleted` correlates to manual-deletion cause;
- segment-processing failure / outage / FFmpeg / restart / recorder-unavailable precedence is deterministic;
- every counted gap has cause/detail/confidence;
- unsupported or insufficient history returns collecting rather than false pass;
- compatibility wrappers preserve critical existing fields during migration.

### Frontend behavior tests

Test visible behavior rather than CSS selectors:

- Health shows Needs Attention before the fleet table;
- healthy selected period shows quiet empty state;
- 24h / 72h selection requests the correct reliability window;
- camera row opens diagnostic drawer;
- drawer renders gap interval, cause, detail and confidence;
- actions route to Cameras / Events / Playback / Operations without auto-starting media except existing explicit event/playback actions;
- historical request failure does not hide realtime state;
- full Playback compatibility table is no longer embedded in Health.

### Verification

Final PR must pass:

- frontend lint;
- frontend tests;
- `vue-tsc --noEmit`;
- Vite production build;
- backend compileall;
- full pytest;
- Docker compose smoke.

## 14. Rollout and backward compatibility

No database migration is required for the page restructuring itself. New structured events reuse the existing Event table.

After deployment:

- new failure/deletion/startup evidence improves diagnosis going forward;
- old gaps without historical evidence may remain unknown;
- existing user deep links to `/health-center` continue to work;
- manual media-start behavior is unchanged.

## 15. Success criteria

Health Center V3 is complete when:

- an operator can identify the current problem and likely cause without scanning multiple large tables;
- missing recording intervals show a persisted/correlated cause when evidence exists and explicit unknown when it does not;
- the realtime websocket path no longer performs historical 24h aggregation every tick;
- Health uses one historical reliability read model rather than separately composing trends + stability in the browser;
- duplicated Operations and Playback detail is removed from Health;
- the code is split into understandable frontend units instead of one monolithic HealthView;
- existing Dashboard, Event Center, Camera, Playback and Operations responsibilities remain intact;
- all CI verification is green and the manual-media-start contract remains preserved.
