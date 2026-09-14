# Motion Detection V2 Design

Date: 2026-09-14
Status: Proposed, approved in chat pending written-spec review
Scope: Complete traditional-computer-vision Motion Detection V2; no AI person/vehicle recognition

## 1. Goals

Motion Detection V2 replaces the current frame-by-frame MOG2/contour-center decision with a stable, low-false-positive pipeline suitable for generating playback anchors.

Primary goals:

- suppress false events caused by light switching, exposure jumps, IR day/night transitions, stream recovery, and background warm-up;
- detect real motion at zone boundaries using actual contour/zone overlap rather than bounding-box center points;
- keep small detection zones usable by sizing motion thresholds against effective detection area rather than always against the whole frame;
- replace unstable single-frame decisions with temporal confidence and hysteresis;
- preserve the existing event policy controls: minimum motion duration, continuous-activity merge window, and minimum event interval;
- expose understandable runtime states and lightweight diagnostics without exposing engineering thresholds to normal users;
- keep recording fully independent from motion-detection failures;
- remain CPU-friendly on the existing reduced-resolution, low-FPS analysis stream.

The product preference is deliberately conservative: lower false positives are more important than catching every transient movement. During whole-frame lighting/exposure transitions, it is acceptable to miss roughly 1–2 seconds of genuine motion while the image stabilizes.

## 2. Non-goals

This version does not add:

- person recognition;
- vehicle recognition;
- YOLO or other neural-network inference;
- face recognition;
- ReID;
- optical flow;
- multi-object tracking;
- GPU inference;
- trajectory analysis;
- user-facing engineering controls for overlap, confidence, warm-up, or global-change thresholds;
- multi-zone many-to-many persistence for a single event.

Those capabilities belong to a later intelligent-event layer rather than the motion detector itself.

## 3. Current behavior and problems

The current detector performs approximately:

1. grayscale + Gaussian blur;
2. MOG2 background subtraction;
3. morphology open/close;
4. contour extraction;
5. minimum contour-area filtering against whole-frame area;
6. bounding-box center-point lookup against enabled zones;
7. single-frame `motion` and `score` output;
8. event state-machine processing.

This creates several known weaknesses:

- MOG2 start-up and reconnection can produce large false foreground masks;
- lighting, exposure, or IR transitions can look like motion across most of the image;
- center-point zone testing can miss real objects crossing zone boundaries;
- small zones inherit a threshold based on the full image and can become unnecessarily insensitive;
- one-frame motion decisions can oscillate near thresholds;
- multi-zone hits currently degrade to the first zone rather than the strongest match;
- active events can be lost when a worker is restarted, disconnected, or cancelled before normal closure;
- runtime status does not explain whether the detector is learning the background or suppressing a global image transition.

## 4. Product decisions

### 4.1 User-facing sensitivity remains simple

The user continues to see only:

- Low
- Medium
- High

All new thresholds are internal implementation details mapped from this sensitivity profile. No advanced engineering panel is added.

### 4.2 Default philosophy

V2 favors low false positives. A short missed movement during a whole-frame transition is acceptable if it avoids creating false playback anchors.

### 4.3 No-zone semantics remain unchanged

- motion detection disabled: no analysis/event generation;
- motion detection enabled with no enabled zones: detect the whole frame;
- motion detection enabled with one or more enabled zones: detect only enabled zones.

## 5. Architecture

The detector is split into three clearly bounded responsibilities.

### `motion_worker.py`

Responsible for:

- RTSP/FFmpeg lifecycle;
- reading raw frames;
- calling the frame analyzer;
- calling the confidence tracker;
- forwarding stable motion into the event state machine;
- selecting the best valid snapshot frame;
- publishing runtime status and diagnostics;
- flushing a confirmed active event on controlled shutdown/restart when appropriate.

It must not contain detailed image-analysis policy.

### `motion_analysis.py` (new)

Responsible for:

- grayscale/blur preprocessing;
- MOG2 background subtraction;
- warm-up;
- whole-frame global-change detection;
- stabilization after a global change;
- morphology and contour extraction;
- cached zone masks;
- contour/zone overlap;
- effective-area thresholds;
- raw motion score;
- primary-zone selection.

### `motion_detection.py`

Responsible for:

- `SensitivityProfile`;
- `MotionConfidenceTracker`;
- `MotionEventStateMachine`;
- event finalization/flush semantics.

The intent is strict separation:

- analysis layer: "what does this frame indicate?";
- confidence layer: "is there stable motion now?";
- event layer: "how should stable motion become a playback event?".

## 6. Data structures

### 6.1 Sensitivity profile

`SensitivityProfile` expands from two fields to an internal policy profile containing at least:

- `var_threshold`;
- `min_area_ratio`;
- `min_zone_overlap_ratio`;
- `global_change_ratio`;
- `global_block_ratio`;
- `confidence_gain`;
- `confidence_decay`;
- `enter_confidence`;
- `exit_confidence`.

Initial target values:

| Setting | Low | Medium | High |
| --- | ---: | ---: | ---: |
| MOG2 variance threshold | 32 | 24 | 16 |
| Minimum motion-area ratio | 1.2% | 0.6% | 0.25% |
| Minimum contour-in-zone overlap | 35% | 25% | 15% |
| Enter confidence | 0.75 | 0.65 | 0.55 |
| Exit confidence | 0.20 | 0.20 | 0.15 |
| Confidence gain | 0.12 | 0.18 | 0.25 |
| Confidence decay | 0.18 | 0.14 | 0.10 |
| Global changed-pixel ratio | 50% | 60% | 70% |
| Global changed-block ratio | 75% | 75% | 75% |

These are internal defaults and may be tuned by tests/field evidence without a database migration.

### 6.2 Analysis result

The frame analyzer returns a structured result rather than a final event-level boolean:

```text
MotionAnalysisResult
- raw_score: float              # 0..1
- primary_zone_id: int | None
- matched_zone_ids: list[int]
- global_change: bool
- warming_up: bool
- stabilizing: bool
- moving_area_ratio: float
- global_change_ratio: float
```

The analyzer does not decide the final stable motion state.

### 6.3 Confidence result

```text
MotionConfidenceResult
- motion: bool
- confidence: float             # 0..1
- transitioned: bool
```

`transitioned` is true when crossing into or out of stable motion.

## 7. Warm-up

Each new analyzer begins in warm-up mode.

Warm-up applies after:

- backend/service start;
- motion detection enable;
- RTSP reconnect;
- stream/path change;
- sensitivity change;
- analysis FPS/width change;
- detection-zone change;
- any worker restart that recreates the analyzer/background model.

Warm-up duration is frame-based, approximately two seconds of analysis frames:

```text
warmup_frames = max(1, round(analysis_fps * 2.0))
```

Examples:

- 3 FPS -> about 6 frames;
- 5 FPS -> about 10 frames;
- 8 FPS -> about 16 frames.

During warm-up:

- frames are still processed by the background model;
- no stable motion is emitted;
- confidence remains/reset to zero;
- warm-up frames cannot become event snapshots;
- runtime state is `warming_up`.

## 8. Global image-change suppression

### 8.1 Purpose

Suppress frame-wide changes caused by:

- lights switching on/off;
- exposure jumps;
- day/night mode transitions;
- IR illuminator transitions;
- stream recovery artifacts;
- camera-wide brightness/color changes.

### 8.2 Detection

Use a path independent of the MOG2 foreground mask:

1. compare current blurred grayscale frame against the previous stable grayscale frame using `absdiff`;
2. mark a pixel changed only when absolute delta meets an internal minimum pixel delta (initial target: 20);
3. calculate changed-pixel ratio;
4. divide the image into a coarse 4x4 grid and calculate how broadly changes are distributed;
5. classify a global image change only when both changed-pixel ratio and changed-block ratio meet the sensitivity profile thresholds.

This dual condition prevents a large nearby person or vehicle concentrated in part of the image from being mistaken for a whole-frame lighting transition.

A block counts as changed only when a meaningful fraction of its pixels cross the pixel-delta threshold; the exact internal block occupancy threshold should be deterministic and covered by tests rather than user configurable.

### 8.3 Stabilization

When a global change is detected:

- current frame cannot produce motion;
- confidence is immediately reset to zero;
- analyzer enters `stabilizing`;
- MOG2/background learning continues;
- frames during stabilization cannot be selected as snapshots.

Target stabilization duration is approximately 1.5 seconds expressed in analysis frames:

```text
stabilization_frames = max(1, round(analysis_fps * 1.5))
```

If another global change occurs while stabilizing, the stabilization window restarts from its full duration.

After the window expires without another global transition, runtime returns to normal `running` detection.

### 8.4 Interaction with an existing active event

Global-change suppression affects only the stable-motion signal, not event persistence directly.

If an event is already active:

- analyzer/confidence emits no motion during stabilization;
- existing merge-gap behavior applies;
- if real motion resumes within the configured merge gap, it remains part of the same event;
- if silence exceeds the normal event closing policy, the event closes at the last valid stable-motion boundary;
- global-change frames never increase event score or replace the snapshot.

This avoids both false anchors and needless fragmentation.

## 9. Zone masks and overlap

### 9.1 Cached masks

Enabled polygons are rasterized into masks at analyzer initialization using the actual analysis-frame dimensions.

For each enabled zone cache:

- zone id;
- binary mask;
- pixel area.

The cache is rebuilt when the worker/analyzer is recreated. Existing zone-update behavior already restarts the worker, so V2 does not require dynamic in-place mask mutation.

### 9.2 Full-frame mode

If no zones are enabled, use a synthetic full-frame effective region and `primary_zone_id = None`.

### 9.3 Contour overlap

Replace bounding-box-center matching with actual intersection:

```text
overlap_ratio = contour_pixels_inside_zone / contour_pixels
```

A contour is eligible for a zone only when this ratio meets the profile's `min_zone_overlap_ratio`.

This intentionally means the question is "how much of the moving object is actually inside this zone?" rather than "is its center point inside?".

### 9.4 Primary zone

If one contour/event candidate overlaps multiple enabled zones, choose the zone with the largest actual intersection area as `primary_zone_id`.

All matched zone IDs may be retained in transient diagnostics, but V2 does not introduce multi-zone event persistence. `MotionEvent.zone_id` remains a single nullable foreign key.

## 10. Effective-area motion threshold

Whole-frame detection continues to compare motion area against whole-frame area.

With enabled zones, the minimum meaningful motion area is calculated against the relevant effective detection region rather than always against the whole frame.

For a contour evaluated against a zone:

```text
minimum_area_pixels = zone_area_pixels * profile.min_area_ratio
```

A contour must satisfy both:

- its effective intersecting motion area is large enough for that zone;
- its contour-in-zone overlap ratio meets the zone-overlap threshold.

This keeps a small doorway/entrance zone responsive without requiring globally higher sensitivity.

## 11. Raw motion score

The analyzer produces `raw_score` in 0..1 from valid motion only.

The score is driven primarily by effective moving-area ratio and zone overlap. It must not require an object to occupy an entire zone before approaching a useful high score.

A simple initial normalization is preferred:

```text
area_score = clamp(effective_area_ratio / (profile.min_area_ratio * 5), 0, 1)
overlap_score = clamp(best_overlap_ratio, 0, 1)
raw_score = clamp(area_score * overlap_score, 0, 1)
```

In full-frame mode, overlap is treated as 1.0 for valid contours.

If multiple valid contours exist, aggregate enough effective area to represent scene activity while avoiding double counting overlapping mask pixels. The implementation may use a union mask of accepted foreground regions for deterministic scoring.

## 12. Temporal confidence and hysteresis

Single-frame `motion=True/False` is removed as the event input.

`MotionConfidenceTracker` keeps confidence in `[0,1]`.

Conceptual behavior per normal analysis frame:

```text
if raw_score > 0:
    confidence += raw_score * profile.confidence_gain
else:
    confidence -= profile.confidence_decay
confidence = clamp(confidence, 0, 1)
```

On warm-up/global-change/stabilization, confidence resets to zero.

Hysteresis:

- enter stable motion only when confidence reaches `enter_confidence`;
- once active, remain active until confidence falls to or below `exit_confidence`;
- values between the two thresholds preserve the previous state.

Consequences:

- one-frame noise does not create motion;
- weak but consistent motion can accumulate;
- a one/two-frame dropout does not immediately end motion;
- low sensitivity rises more slowly and falls faster;
- high sensitivity rises faster and falls more slowly.

## 13. Event policy remains separate

`MotionEventStateMachine` remains responsible for the user-configured event strategy only:

- minimum motion duration;
- continuous activity merge window;
- minimum event interval/playback-anchor density.

It receives stable motion from the confidence tracker.

No global-change or image-analysis thresholds are added to the event state machine.

## 14. Event finalization on worker stop/restart

V2 closes the existing event-loss gap.

Add explicit state-machine finalization/flush behavior:

- an unconfirmed candidate that has not met minimum duration is discarded;
- a confirmed active event is emitted on controlled worker shutdown/restart/disconnect using the last valid motion time (or an existing pending-end time if one exists);
- a flush must not fabricate additional duration from warm-up/stabilization/no-frame time;
- a flushed event preserves the best valid snapshot collected before interruption;
- the same active event must not be emitted twice.

This applies when settings/zone changes restart a worker and when a stream disconnect triggers supervision/reconnect.

## 15. Snapshot policy

A motion event snapshot may only come from a frame that:

- is outside warm-up;
- is outside stabilization;
- is not classified as global change;
- contributes valid motion evidence.

The worker tracks the strongest valid frame using a deterministic quality key, preferring higher stable confidence and then raw score.

Global-change frames, background-learning frames, and suppressed frames can never replace the event's best snapshot.

## 16. Runtime states

Extend runtime state to:

- `disabled`;
- `starting`;
- `warming_up`;
- `running`;
- `stabilizing`;
- `reconnecting`;
- `error`;
- `stopped`.

User-facing Chinese labels:

- `warming_up` -> `背景学习中`;
- `running` -> `检测中`;
- `stabilizing` -> `画面稳定中`;
- existing labels remain for the other states.

The worker/manager should publish the most useful current algorithm state rather than always reporting `running` simply because frames are arriving.

## 17. Runtime diagnostics

Expose lightweight, read-only transient diagnostics through the existing runtime response. Suggested fields:

- `confidence: float | None`;
- `raw_score: float | None`;
- `moving_area_ratio: float | None`;
- `global_change_ratio: float | None`;
- `primary_zone_id: int | None`;
- `global_change: bool`.

These values are in memory only and do not require database persistence.

The frontend may present a restrained diagnostic summary, for example:

- current state;
- confidence percentage;
- current/primary zone name when available;
- image-change state (`正常` / `全局变化抑制`);
- most recent analyzed frame time.

Engineering thresholds must remain hidden.

Diagnostics are informational only and must not introduce a new control surface.

## 18. Frontend scope

`MotionDetectionPanel.vue` keeps the current user controls:

- master enable;
- sensitivity Low/Medium/High;
- analysis FPS;
- minimum motion duration;
- continuous-activity merge;
- minimum event interval;
- zone editor.

V2 frontend changes are limited to:

- support new runtime states;
- show clear user-facing explanations for `warming_up` and `stabilizing`;
- add a compact read-only diagnostic area using the runtime fields above;
- preserve the current no-enabled-zone = full-frame explanation;
- do not expose internal V2 thresholds.

No media auto-start behavior changes are allowed.

## 19. Event metadata

Newly persisted V2 events use:

```json
{"detector":"motion-v2"}
```

Existing events remain untouched.

No schema migration is required for this change because `metadata_json` already exists.

## 20. Database and API compatibility

No new user-configurable database columns are required.

Existing persisted settings remain authoritative:

- `enabled`;
- `sensitivity`;
- `analysis_fps`;
- `analysis_width`;
- `min_duration_ms`;
- `merge_gap_ms`;
- `event_min_interval_ms`.

Existing camera settings work immediately with V2. Users do not need to reopen or resave settings after upgrade.

API additions are backward-compatible optional runtime diagnostic fields plus the expanded runtime state enum.

Motion event listing, snapshots, playback timeline, and event feed APIs do not change shape.

## 21. Error isolation

Motion detection remains operationally independent from recording.

If V2 analysis raises an exception:

- the motion worker may enter `error`/`reconnecting` according to existing supervision;
- recording must continue unaffected;
- no exception from motion analysis may propagate into recorder-manager/recording worker lifecycles;
- reconnect recreates the analyzer and therefore runs warm-up again.

The analysis path must not block the recorder pipeline or use the recording stream as a mandatory dependency.

## 22. Performance constraints

V2 continues to analyze the dedicated low-FPS, reduced-width stream (normally 3–8 FPS and around 640 px analysis width).

Permitted additional operations include:

- grayscale `absdiff`;
- coarse block statistics;
- binary mask operations;
- contour masks;
- zone-mask intersections;
- small in-memory confidence state.

V2 does not introduce neural inference, optical flow, or tracking.

Implementation should avoid repeated allocation of zone masks and avoid rasterizing polygons every frame.

The worker must continue consuming frames at the configured analysis rate without unbounded rawvideo-pipe accumulation. If processing ever becomes slower than the configured input rate in profiling/tests, reduce per-frame allocations/operations rather than buffering indefinitely.

## 23. Testing strategy

This is high-risk backend/media-adjacent behavior and requires targeted regression tests plus the existing full CI suite.

Use deterministic NumPy-generated frames where possible; do not require real camera streams for algorithm unit tests.

Required behavior tests include at least:

1. warm-up does not emit stable motion;
2. normal real movement is detected after warm-up;
3. whole-frame brightness transition is classified as global change and does not emit motion;
4. a large local object does not become global change merely because it occupies substantial area;
5. stabilization suppresses motion output;
6. repeated global transitions extend/restart stabilization;
7. detection resumes after stabilization;
8. insufficient contour/zone overlap does not count;
9. sufficient contour/zone overlap counts even when the contour/bounding-box center lies outside the zone;
10. small zones use effective zone area rather than whole-frame thresholding;
11. no enabled zones means full-frame detection;
12. disabled zones are ignored;
13. multiple matching zones select the largest-intersection primary zone;
14. one-frame noise cannot cross the enter threshold;
15. repeated valid motion accumulates confidence and eventually enters stable motion;
16. one/two weak or missing frames do not immediately exit stable motion;
17. stable motion exits only after confidence crosses the lower exit threshold;
18. Low/Medium/High profiles preserve expected ordering of sensitivity;
19. global-change/warm-up frames cannot become snapshots;
20. snapshot selection prefers the strongest valid motion frame;
21. event strategy still respects minimum duration, merge gap, and event minimum interval;
22. a confirmed active event flushes once on worker stop/restart/disconnect;
23. an unconfirmed candidate is discarded on flush;
24. reconnect creates a fresh analyzer and warm-up cycle;
25. runtime reports `warming_up`, `stabilizing`, and `running` correctly;
26. motion-analysis failure remains isolated from recording components.

The existing backend full pytest, frontend tests/build, and Docker smoke remain required before merge.

## 24. Rollout strategy

V2 becomes the default motion detector directly; there is no user-visible v1/v2 switch.

Rollout properties:

- existing settings are reused unchanged;
- no required database migration for V2-specific thresholds;
- new events identify themselves as `motion-v2` in metadata;
- runtime diagnostics provide field-debug visibility;
- reverting the implementation does not require rewriting stored user settings.

The deployment entry remains unchanged:

```bash
git pull && ./deploy.sh
```

## 25. Acceptance criteria

The V2 implementation is accepted when all of the following are true:

- turning lights on/off does not create a burst of motion events;
- IR/day-night or exposure transitions are suppressed and enter a visible stabilization state;
- a restart/reconnect does not create a false event during background learning;
- a restart/reconnect does not silently lose an already-confirmed active event;
- transient sensor/background noise produces materially fewer anchors;
- real movement crossing a detection-zone edge is not missed solely because its center point remains outside;
- small detection zones remain usable at normal sensitivity;
- a large local person/vehicle-shaped change is not automatically mistaken for a global image transition;
- genuine continuous movement reliably reaches stable motion;
- brief one/two-frame dropouts do not cause motion-state oscillation;
- no-enabled-zone semantics remain full-frame detection;
- only Low/Medium/High sensitivity is user-facing; internal engineering parameters remain hidden;
- runtime UI clearly distinguishes background learning, normal detection, and image stabilization;
- runtime diagnostics are sufficient to inspect confidence, raw score, image-change ratio, and active zone without changing settings;
- event feed/timeline/snapshot compatibility is preserved;
- recording remains unaffected by motion-worker failures;
- all new targeted tests and existing CI checks pass.

## 26. Expected implementation surface

Primary backend files:

- `backend/app/services/motion_analysis.py` (new)
- `backend/app/services/motion_detection.py`
- `backend/app/services/motion_worker.py`
- `backend/app/services/motion_manager.py`
- `backend/app/schemas/motion.py`
- motion-related backend tests

Primary frontend files:

- `frontend/src/MotionDetectionPanel.vue`
- motion-related frontend tests

No unrelated detector improvements, AI classification, playback changes, recording-format changes, or deployment-entry changes are part of this work.
