# Motion Detection V2 Design

Date: 2026-09-14
Status: Proposed, approved in chat pending written-spec review
Scope: Complete traditional-computer-vision Motion Detection V2; no AI person/vehicle recognition

## 1. Goals

Motion Detection V2 replaces the current frame-by-frame MOG2/contour-center decision with a stable, low-false-positive pipeline suitable for generating playback anchors.

Primary goals:

- suppress false events caused by light switching, exposure jumps, IR day/night transitions, stream recovery, camera-wide shake/change, and background warm-up;
- detect real motion at zone boundaries using actual contour/zone overlap rather than bounding-box center points;
- keep small detection zones usable by sizing motion thresholds against effective detection area rather than always against the whole frame;
- replace unstable single-frame decisions with temporal confidence and hysteresis;
- preserve the existing event policy controls: minimum motion duration, continuous-activity merge window, and minimum event interval;
- expose understandable runtime states and lightweight diagnostics without exposing engineering thresholds to normal users;
- close the current active-event loss gap on worker restart/disconnect;
- keep recording fully independent from motion-detection failures;
- remain CPU-friendly on the existing reduced-resolution, low-FPS analysis stream.

The product preference is deliberately conservative: lower false positives are more important than catching every transient movement. During whole-frame lighting/exposure transitions, it is acceptable to miss roughly 1–2 seconds of genuine motion while the image stabilizes.

## 2. Non-goals

This version does not add person/vehicle recognition, YOLO or other neural inference, face recognition, ReID, optical flow, multi-object tracking, GPU inference, trajectory analysis, user-facing engineering controls for internal thresholds, or multi-zone many-to-many event persistence.

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

Known weaknesses:

- MOG2 start-up and reconnection can produce large false foreground masks;
- lighting, exposure, IR, or camera-wide transitions can look like motion across most of the image;
- center-point zone testing can miss real objects crossing zone boundaries;
- small zones inherit a threshold based on the full image and can become unnecessarily insensitive;
- one-frame motion decisions can oscillate near thresholds;
- multi-zone hits currently degrade to the first zone rather than the strongest match;
- confirmed active events can be lost when a worker restarts/disconnects before normal closure;
- runtime status does not explain background learning or global-image stabilization.

## 4. Product decisions

### 4.1 Simple user-facing sensitivity

The user continues to see only Low / Medium / High. All new thresholds are internal implementation details mapped from the sensitivity profile. No advanced engineering panel is added.

### 4.2 Low-false-positive priority

V2 favors low false positives. A short missed movement during a whole-frame transition is acceptable if it prevents false playback anchors.

### 4.3 No-zone semantics remain unchanged

- detection disabled: no analysis/event generation;
- detection enabled with no enabled zones: detect the whole frame;
- detection enabled with one or more enabled zones: detect only enabled zones.

## 5. Architecture

### `motion_worker.py`

Owns RTSP/FFmpeg lifecycle, frame reads, calls into analyzer/confidence/event layers, best-snapshot selection, runtime publication, and confirmed-event flush on stop/restart/disconnect. It must not contain detailed image-analysis policy.

### `motion_analysis.py` (new)

Owns grayscale/blur preprocessing, MOG2, warm-up, global-change detection, stabilization, morphology/contours, cached zone masks, contour/zone overlap, effective-area filtering, raw scoring, and primary-zone selection.

### `motion_detection.py`

Owns `SensitivityProfile`, `MotionConfidenceTracker`, `MotionEventStateMachine`, and event finalization/flush semantics.

Strict responsibility split:

- analysis layer: what does this frame indicate?
- confidence layer: is there stable motion now?
- event layer: how should stable motion become a playback event?

## 6. Core data structures

### 6.1 SensitivityProfile

Internal fields include at least:

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
| Enter confidence | 0.75 | 0.60 | 0.55 |
| Exit confidence | 0.20 | 0.20 | 0.15 |
| Confidence gain/frame | 0.25 | 0.30 | 0.35 |
| Confidence decay/frame | 0.35 | 0.25 | 0.18 |
| Global changed-pixel ratio | 50% | 60% | 70% |
| Global changed-block ratio | 75% | 75% | 75% |

These are internal starting values and may be tuned by deterministic tests and field evidence without a database migration. The ordering must remain semantically consistent: Low is most conservative, High is most sensitive.

### 6.2 MotionAnalysisResult

```text
MotionAnalysisResult
- raw_score: float              # 0..1, valid motion strength
- primary_zone_id: int | None
- matched_zone_ids: list[int]
- global_change: bool
- warming_up: bool
- stabilizing: bool
- moving_area_ratio: float
- global_change_ratio: float
```

The analyzer does not decide the final stable-motion state.

### 6.3 MotionConfidenceResult

```text
MotionConfidenceResult
- motion: bool
- confidence: float             # 0..1
- transitioned: bool
```

`transitioned` is true only when crossing into or out of stable motion.

## 7. Warm-up

Each new analyzer begins in warm-up mode after service start, detection enable, RTSP reconnect, stream/path change, sensitivity/FPS/width change, zone change, or any worker restart that recreates the background model.

```text
warmup_frames = max(1, round(analysis_fps * 2.0))
```

Examples: 3 FPS -> ~6 frames; 5 FPS -> ~10; 8 FPS -> ~16.

During warm-up:

- frames continue feeding the background model;
- no stable motion is emitted;
- confidence is zero;
- frames cannot become event snapshots;
- runtime state is `warming_up`.

## 8. Global image-change suppression

### 8.1 Detection purpose

Suppress light switching, exposure changes, day/night or IR transitions, stream recovery artifacts, and camera-wide image changes/shake.

### 8.2 Detection algorithm

Global-change detection is independent of the MOG2 foreground mask.

Normal running mode maintains a grayscale reference frame from the immediately previous accepted normal frame.

For each frame:

1. compute `absdiff(reference_gray, current_gray)`;
2. count a pixel changed only when absolute delta is at least 20 (initial internal constant);
3. calculate total changed-pixel ratio;
4. split the image into a 4x4 grid;
5. mark a block changed when at least 30% of that block's pixels cross the pixel-delta threshold (initial internal constant);
6. calculate changed-block ratio;
7. classify `global_change=true` only when both changed-pixel ratio and changed-block ratio meet the sensitivity profile thresholds.

The dual condition is mandatory: a large nearby person/vehicle concentrated in part of the frame must not become a global transition solely because it occupies substantial area.

### 8.3 Reference-frame semantics

The reference must not remain pinned to the pre-transition image, otherwise a real light switch would continuously look "global" forever.

Rules:

- in normal running mode, a non-global frame becomes the next `reference_gray` after analysis;
- on the first global-change frame, immediately set `reference_gray=current_gray` and enter stabilization;
- while stabilizing, compare each frame against the previous stabilization frame (rolling reference), then advance the reference to the current frame;
- if another frame-to-frame global transition occurs during stabilization, restart the full stabilization window;
- when stabilization completes, the latest frame is already the reference for the new scene state.

### 8.4 Stabilization

On global change:

- current frame cannot produce motion;
- confidence resets to zero;
- runtime becomes `stabilizing`;
- MOG2/background learning continues;
- suppressed frames cannot become snapshots.

```text
stabilization_frames = max(1, round(analysis_fps * 1.5))
```

A repeated global transition restarts this countdown. After the countdown expires without another global transition, normal `running` detection resumes.

### 8.5 Interaction with an active event

Global-change suppression affects the stable-motion input, not event persistence directly.

If an event is already active:

- stabilization contributes no motion and no score;
- normal merge-gap behavior applies;
- motion resuming within the merge window remains the same event;
- if closing conditions are reached, the event ends at the last valid stable-motion boundary, never at an arbitrary stabilization frame;
- suppressed frames cannot increase score or replace the snapshot.

## 9. Zone masks and overlap

Enabled polygons are rasterized once at analyzer initialization using actual analysis dimensions. Cache zone id, binary mask, and pixel area. Existing zone edits restart the worker, so V2 does not need in-place mask mutation.

If no zones are enabled, use a synthetic full-frame region and `primary_zone_id=None`.

Replace center-point matching with:

```text
overlap_ratio = contour_pixels_inside_zone / contour_pixels
```

A contour is eligible only when its overlap meets `min_zone_overlap_ratio`.

If multiple zones match, `primary_zone_id` is the zone with the largest actual intersection area. `matched_zone_ids` may remain transient diagnostics, while `MotionEvent.zone_id` stays a single nullable foreign key.

## 10. Effective-area motion threshold

Whole-frame mode compares motion area against whole-frame area.

With enabled zones:

```text
minimum_area_pixels = zone_area_pixels * profile.min_area_ratio
```

A contour must satisfy both minimum intersecting area and minimum contour-in-zone overlap. This keeps a small doorway/entrance zone responsive without raising global sensitivity.

## 11. Raw motion score

`raw_score` is 0..1 and is produced only from valid, accepted motion.

Initial normalization:

```text
area_score = clamp(effective_area_ratio / (profile.min_area_ratio * 5), 0, 1)
overlap_score = clamp(best_overlap_ratio, 0, 1)
raw_score = clamp(area_score * overlap_score, 0, 1)
```

Full-frame mode treats overlap as 1.0. With multiple valid contours, use a union mask of accepted foreground pixels to avoid double-counting overlapping regions.

`raw_score` is primarily diagnostic and snapshot-ranking evidence; eligibility filtering has already removed sub-threshold noise.

## 12. Temporal confidence and hysteresis

Single-frame event input is removed. `MotionConfidenceTracker` maintains confidence in `[0,1]`.

For a normal frame with accepted motion evidence:

```text
evidence_weight = 0.6 + 0.4 * raw_score
confidence += profile.confidence_gain * evidence_weight
```

For a normal frame with no accepted motion:

```text
confidence -= profile.confidence_decay
```

Then clamp to `[0,1]`.

Warm-up/global-change/stabilization hard-reset confidence to zero.

Hysteresis:

- enter stable motion when confidence >= `enter_confidence`;
- once active, remain active until confidence <= `exit_confidence`;
- values between thresholds preserve the current state.

This gives roughly a few analysis frames of temporal confirmation rather than several seconds, leaving the user-configured minimum-motion-duration control meaningful as a separate event policy.

Required behavior:

- one-frame noise does not create stable motion;
- repeated valid motion accumulates quickly enough for practical monitoring;
- one/two weak or missing frames do not immediately end stable motion;
- Low rises more conservatively and falls faster than High.

## 13. Event policy remains separate

`MotionEventStateMachine` continues to own only:

- minimum motion duration;
- continuous activity merge window;
- minimum event interval/playback-anchor density.

It receives stable motion from the confidence tracker. No image-analysis thresholds are moved into the event state machine.

## 14. Event finalization on worker stop/restart/disconnect

V2 closes the current event-loss gap with an explicit `flush/finalize` path.

Rules:

- an unconfirmed candidate that has not met minimum duration is discarded;
- a confirmed active event is emitted once on controlled worker shutdown, settings/zone restart, or stream disconnect;
- the end timestamp is the last valid stable-motion timestamp, or an existing pending-end timestamp if one already exists and is earlier/more accurate;
- flush must never fabricate duration from warm-up, stabilization, missing frames, or reconnect delay;
- the best valid snapshot accumulated before interruption is preserved;
- repeated cleanup paths must not emit the same event twice.

The worker performs finalization before supervision creates a replacement analyzer.

## 15. Snapshot policy

An event snapshot may only come from a frame that is outside warm-up/stabilization, is not global change, and contributes accepted motion evidence.

The worker ranks valid candidates deterministically by stable confidence first and raw score second. Suppressed/background-learning frames can never replace the best snapshot.

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

User-facing labels include:

- `warming_up` -> `背景学习中`;
- `running` -> `检测中`;
- `stabilizing` -> `画面稳定中`.

The worker/manager publishes the actual algorithm state rather than reporting `running` merely because frames are arriving.

## 17. Runtime diagnostics

Expose transient read-only diagnostics through the existing runtime response:

- `confidence: float | None`;
- `raw_score: float | None`;
- `moving_area_ratio: float | None`;
- `global_change_ratio: float | None`;
- `primary_zone_id: int | None`;
- `global_change: bool`.

No persistence is required.

The frontend presents a restrained diagnostic summary such as current state, confidence percentage, primary zone name, image-change state (`正常` / `全局变化抑制`), and most recent analyzed-frame time. Internal thresholds remain hidden and diagnostics are not controls.

## 18. Frontend scope

`MotionDetectionPanel.vue` retains the current user controls: master enable, Low/Medium/High sensitivity, analysis FPS, minimum motion duration, continuous-activity merge, minimum event interval, and zone editor.

V2 frontend changes:

- support `warming_up` and `stabilizing` runtime states;
- explain these states in user language;
- add a compact read-only diagnostic area using runtime fields;
- preserve the no-enabled-zone = full-frame explanation;
- do not expose internal V2 engineering parameters;
- do not change manual media-start behavior.

## 19. Event metadata

New events use:

```json
{"detector":"motion-v2"}
```

Existing events remain untouched. No schema migration is needed for `metadata_json`.

## 20. Database/API compatibility

No new user-configurable database columns are required. Existing persisted settings remain authoritative:

- `enabled`;
- `sensitivity`;
- `analysis_fps`;
- `analysis_width`;
- `min_duration_ms`;
- `merge_gap_ms`;
- `event_min_interval_ms`.

Existing settings work immediately with V2 without resaving.

API changes are backward-compatible optional runtime diagnostics plus the expanded runtime state enum. Motion event listing, snapshots, playback timeline, and event feed shapes remain unchanged.

## 21. Error isolation

Motion detection remains operationally independent from recording.

If analysis fails:

- the motion worker may enter `error`/`reconnecting` under existing supervision;
- recording continues unaffected;
- no motion-analysis exception may propagate into recorder/recording worker lifecycles;
- reconnect creates a fresh analyzer and therefore a fresh warm-up cycle.

The analysis path remains on the dedicated low-rate stream and must not make the recording stream a mandatory dependency.

## 22. Performance constraints

V2 continues using the reduced-width, low-FPS analysis stream (normally 3–8 FPS, around 640 px width).

Allowed added operations are grayscale `absdiff`, coarse block statistics, binary masks, contour masks, zone intersections, and small in-memory confidence state. No neural inference, optical flow, or tracking.

Avoid repeated zone-mask rasterization and unnecessary per-frame allocations. The worker must consume frames at the configured analysis rate without unbounded rawvideo-pipe accumulation; if profiling shows processing slower than input, optimize/reuse masks and arrays rather than buffering indefinitely.

## 23. Testing strategy

This is high-risk backend/media-adjacent behavior. Use deterministic NumPy-generated frames where possible and keep the existing full CI suite.

Required behavior tests include at least:

1. warm-up emits no stable motion;
2. real movement is detected after warm-up;
3. whole-frame brightness transition is global change and emits no motion;
4. after a global transition, the rolling stabilization reference converges to the new scene instead of repeatedly comparing to the pre-transition scene;
5. a large local object is not global change merely because it occupies substantial area;
6. stabilization suppresses motion output;
7. repeated global transitions restart stabilization;
8. detection resumes after stabilization;
9. insufficient contour/zone overlap does not count;
10. sufficient overlap counts even when contour/bounding-box center lies outside the zone;
11. small zones use effective zone area rather than whole-frame thresholding;
12. no enabled zones means full-frame detection;
13. disabled zones are ignored;
14. multiple matching zones select the largest-intersection primary zone;
15. one-frame noise cannot cross the enter threshold;
16. repeated valid motion accumulates confidence and enters stable motion within a practical number of analysis frames;
17. one/two weak or missing frames do not immediately exit stable motion;
18. stable motion exits only after crossing the lower exit threshold;
19. Low/Medium/High profiles preserve expected sensitivity ordering;
20. global-change/warm-up frames cannot become snapshots;
21. snapshot selection prefers the strongest valid motion frame;
22. event strategy still respects minimum duration, merge gap, and event minimum interval;
23. a confirmed active event flushes exactly once on stop/restart/disconnect using the last valid motion boundary;
24. an unconfirmed candidate is discarded on flush;
25. reconnect creates a fresh analyzer/warm-up cycle;
26. runtime reports `warming_up`, `stabilizing`, and `running` correctly with diagnostics;
27. motion-analysis failure remains isolated from recording components.

Before merge, frontend tests/build, backend full pytest, and Docker smoke must all pass.

## 24. Rollout strategy

V2 becomes the default detector directly; there is no user-visible v1/v2 switch.

- existing settings are reused unchanged;
- no V2 threshold migration is required;
- new events identify `motion-v2` in metadata;
- runtime diagnostics provide field-debug visibility;
- reverting implementation does not require rewriting stored settings.

Deployment entry remains exactly:

```bash
git pull && ./deploy.sh
```

## 25. Acceptance criteria

V2 is accepted when:

- turning lights on/off does not create bursts of motion events;
- IR/day-night or exposure transitions are suppressed and show stabilization state;
- a stable post-transition image exits stabilization rather than looping indefinitely;
- restart/reconnect creates no false event during background learning;
- restart/reconnect does not silently lose an already-confirmed active event;
- transient sensor/background noise creates materially fewer anchors;
- real movement crossing a zone edge is not missed solely because its center stays outside;
- small zones remain usable at normal sensitivity;
- a large local object is not automatically mistaken for global image change;
- genuine continuous movement reaches stable motion promptly and then obeys the configured minimum-motion-duration policy;
- brief one/two-frame dropouts do not cause motion-state oscillation;
- no-enabled-zone semantics remain full-frame detection;
- only Low/Medium/High sensitivity is user-facing;
- runtime UI distinguishes background learning, normal detection, and stabilization;
- diagnostics expose enough information to inspect confidence, raw score, image-change ratio, and active zone;
- event feed/timeline/snapshot compatibility is preserved;
- recording remains unaffected by motion-worker failures;
- all targeted tests and existing CI checks pass.

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

No unrelated AI classification, playback changes, recording-format changes, or deployment-entry changes are part of this work.
