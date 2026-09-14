# Motion Detection V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single-frame motion decision with a low-false-positive Motion Detection V2 pipeline that adds warm-up, global-change suppression, real zone overlap, effective-area thresholds, temporal confidence/hysteresis, event flush safety, runtime diagnostics, and restrained frontend visibility without adding AI recognition.

**Architecture:** Keep RTSP/FFmpeg lifecycle in `motion_worker.py`, move frame-analysis policy into a new `motion_analysis.py`, and keep sensitivity/confidence/event policy in `motion_detection.py`. The analyzer returns structured frame evidence, the confidence tracker turns evidence into stable motion, and the existing event state machine continues to turn stable motion into playback anchors. Runtime diagnostics are transient and flow worker -> manager -> API schema -> `MotionDetectionPanel.vue`.

**Tech Stack:** Python 3, FastAPI, asyncio, OpenCV, NumPy, SQLAlchemy, Pydantic, pytest; Vue 3 + TypeScript, Element Plus, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-14-motion-detection-v2-design.md`

## Global Constraints

- Preserve deployment entry exactly: `git pull && ./deploy.sh`.
- Preserve no-zone semantics: disabled means no detection; enabled with zero enabled zones means full-frame detection; enabled with zones means only enabled zones.
- User-facing sensitivity stays only `low | medium | high`; no engineering threshold controls are added.
- Favor low false positives; during whole-frame transitions it is acceptable to miss roughly 1–2 seconds of genuine motion.
- Do not add person/vehicle recognition, YOLO, face recognition, ReID, optical flow, multi-object tracking, GPU inference, or trajectory analysis.
- Do not add a multi-zone event persistence schema; `MotionEvent.zone_id` remains a single nullable zone.
- Recording must remain independent from motion-detection failure or restart.
- Motion Detection V2 must remain on the existing low-FPS, reduced-resolution analysis stream.
- Warm-up/global-change/stabilization frames must never become event snapshots.
- Existing event controls remain authoritative: `min_duration_ms`, `merge_gap_ms`, `event_min_interval_ms`.
- No new database migration is required for V2 detector thresholds or runtime diagnostics.

---

## File Structure

**Create**
- `backend/app/services/motion_analysis.py` — frame preprocessing, MOG2, warm-up, global-change suppression, stabilization, cached zone masks, overlap/effective-area scoring, primary-zone selection.
- `backend/tests/test_motion_analysis.py` — deterministic NumPy/OpenCV behavior tests for the V2 analyzer.

**Modify**
- `backend/app/services/motion_detection.py` — expand `SensitivityProfile`, add `MotionConfidenceTracker`, add explicit event-state flush semantics.
- `backend/app/services/motion_worker.py` — remove image-analysis policy, orchestrate analyzer + confidence tracker + event state machine, publish diagnostics, select valid snapshots, flush confirmed events on exit.
- `backend/app/services/motion_manager.py` — accept richer status/diagnostic callbacks and persist detector version `motion-v2`.
- `backend/app/schemas/motion.py` — add `warming_up` / `stabilizing` runtime states and transient diagnostic fields.
- `backend/app/api/motion_detection.py` — return the richer runtime payload without changing settings persistence.
- `backend/tests/test_motion_detection.py` — sensitivity profile, confidence/hysteresis, and flush behavior.
- `backend/tests/test_motion_worker.py` — orchestration/snapshot/runtime-state behavior, while retaining command/path/scaling tests.
- `backend/tests/test_motion_manager.py` — diagnostic propagation and reconnect/restart behavior.
- `backend/tests/test_motion_api.py` — runtime response schema/regression coverage.
- `frontend/src/MotionDetectionPanel.vue` — add `warming_up`/`stabilizing` labels and restrained diagnostics summary; keep settings surface unchanged.
- Existing frontend test file that covers `MotionDetectionPanel.vue`; if none exists, create `frontend/src/MotionDetectionPanel.test.ts`.

---

### Task 1: Expand Sensitivity Policy and Add Confidence/Hysteresis

**Files:**
- Modify: `backend/app/services/motion_detection.py`
- Test: `backend/tests/test_motion_detection.py`

**Interfaces:**
- Produces: `SensitivityProfile(var_threshold, min_area_ratio, min_zone_overlap_ratio, global_change_ratio, global_block_ratio, confidence_gain, confidence_decay, enter_confidence, exit_confidence)`.
- Produces: `MotionConfidenceResult(motion: bool, confidence: float, transitioned: bool)`.
- Produces: `MotionConfidenceTracker(profile: SensitivityProfile)` with `update(raw_score: float, *, suppressed: bool = False) -> MotionConfidenceResult` and `reset() -> MotionConfidenceResult`.
- Preserves: `sensitivity_profile(level: str) -> SensitivityProfile` and `MotionEventStateMachine` public update behavior.

- [ ] **Step 1: Write failing profile and confidence tests**

Add tests that assert profile ordering and practical temporal confirmation:

```python
def test_sensitivity_profiles_order_false_positive_tolerance() -> None:
    low = sensitivity_profile("low")
    medium = sensitivity_profile("medium")
    high = sensitivity_profile("high")

    assert (low.var_threshold, medium.var_threshold, high.var_threshold) == (32, 24, 16)
    assert low.min_area_ratio > medium.min_area_ratio > high.min_area_ratio
    assert low.min_zone_overlap_ratio > medium.min_zone_overlap_ratio > high.min_zone_overlap_ratio
    assert low.enter_confidence > medium.enter_confidence > high.enter_confidence
    assert low.confidence_gain < medium.confidence_gain < high.confidence_gain
    assert low.confidence_decay > medium.confidence_decay > high.confidence_decay
    assert low.global_change_ratio < medium.global_change_ratio < high.global_change_ratio


def test_confidence_tracker_accumulates_valid_motion_and_uses_hysteresis() -> None:
    tracker = MotionConfidenceTracker(sensitivity_profile("medium"))

    first = tracker.update(0.25)
    assert first.motion is False
    assert 0.0 < first.confidence < 0.65

    result = first
    for _ in range(8):
        result = tracker.update(0.25)
        if result.motion:
            break
    assert result.motion is True
    assert result.transitioned is True

    still_active = tracker.update(0.0)
    assert still_active.motion is True
    assert still_active.confidence > 0.20

    result = still_active
    for _ in range(10):
        result = tracker.update(0.0)
        if not result.motion:
            break
    assert result.motion is False
    assert result.transitioned is True


def test_confidence_tracker_suppression_resets_state() -> None:
    tracker = MotionConfidenceTracker(sensitivity_profile("high"))
    for _ in range(6):
        tracker.update(1.0)
    reset = tracker.update(1.0, suppressed=True)
    assert reset.motion is False
    assert reset.confidence == 0.0
```

- [ ] **Step 2: Run targeted tests and verify RED**

```bash
cd backend && uv run pytest tests/test_motion_detection.py -q
```

Expected: FAIL because the expanded profile fields and `MotionConfidenceTracker` do not yet exist.

- [ ] **Step 3: Implement exact internal profiles and confidence tracker**

Use these initial values:

```python
_PROFILES = {
    "low": SensitivityProfile(32, 0.012, 0.35, 0.50, 0.75, 0.12, 0.18, 0.75, 0.20),
    "medium": SensitivityProfile(24, 0.006, 0.25, 0.60, 0.75, 0.18, 0.14, 0.65, 0.20),
    "high": SensitivityProfile(16, 0.0025, 0.15, 0.70, 0.75, 0.25, 0.10, 0.55, 0.15),
}
```

Prefer keyword construction in production code for readability. For accepted motion evidence, update confidence exactly as approved in the spec:

```python
evidence_weight = 0.6 + 0.4 * raw_score
confidence += profile.confidence_gain * evidence_weight
```

For no accepted motion, subtract `profile.confidence_decay`. Clamp to `[0,1]`; enter stable motion at `enter_confidence`, exit only at/below `exit_confidence`. `suppressed=True` hard-resets confidence and stable motion.

- [ ] **Step 4: Run targeted tests and verify GREEN**

```bash
cd backend && uv run pytest tests/test_motion_detection.py -q
```

Expected: PASS for new profile/confidence tests and all pre-existing event-state tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/motion_detection.py backend/tests/test_motion_detection.py
git commit -m "feat: add motion confidence tracking"
```

---

### Task 2: Build the V2 Frame Analyzer

**Files:**
- Create: `backend/app/services/motion_analysis.py`
- Create: `backend/tests/test_motion_analysis.py`

**Interfaces:**
- Consumes: `SensitivityProfile` and `sensitivity_profile()` from Task 1.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class MotionAnalysisResult:
    raw_score: float
    primary_zone_id: int | None
    matched_zone_ids: list[int]
    global_change: bool
    warming_up: bool
    stabilizing: bool
    moving_area_ratio: float
    global_change_ratio: float
```

- Produces: `MotionFrameAnalyzer(sensitivity: str, *, analysis_fps: int)`.
- Produces: `analyze(frame: np.ndarray, zones: list[dict[str, Any]]) -> MotionAnalysisResult`.
- Analyzer caches enabled-zone masks for the first observed frame dimensions; worker recreation invalidates the cache.

- [ ] **Step 1: Write failing warm-up and normal-motion tests**

Use deterministic 360x640 black frames and white rectangles. Feed exactly `max(1, round(fps * 2.0))` warm-up frames. Assert warm-up frames report `warming_up=True`, `raw_score=0`, no primary zone, and cannot create valid motion evidence. Then assert local motion after warm-up yields positive `raw_score`.

- [ ] **Step 2: Write failing global-change/stabilization tests**

Cover:

```text
full-frame black -> full-frame white => global_change=True, raw_score=0
stabilization frames => stabilizing=True, raw_score=0
second whole-frame transition during stabilization => stabilization window restarts
post-stabilization local rectangle => raw_score>0
large local rectangle affecting only part of the grid => global_change=False
reference rolls forward during stabilization and converges to the new scene
```

Use the approved constants exactly:

```text
pixel_delta_threshold = 20
global grid = 4x4
block_changed when >=30% of block pixels exceed pixel delta
global change only when changed_pixel_ratio >= profile.global_change_ratio AND changed_block_ratio >= profile.global_block_ratio
```

- [ ] **Step 3: Write failing zone-overlap/effective-area tests**

Cover:

```text
no enabled zones => full-frame mode, primary_zone_id=None
disabled zones ignored
center outside zone but overlap >= threshold => accepted
small edge touch below overlap threshold => rejected
small zone + valid local motion => accepted using zone area, not whole-frame area
multi-zone hit => primary zone is largest actual intersection area
```

The accepted motion area for a zone is foreground pixels actually inside the zone. Minimum area pixels are `zone_area_pixels * profile.min_area_ratio`.

- [ ] **Step 4: Run analyzer tests and verify RED**

```bash
cd backend && uv run pytest tests/test_motion_analysis.py -q
```

Expected: FAIL because `motion_analysis.py` does not exist.

- [ ] **Step 5: Implement `motion_analysis.py`**

Implementation rules:

```text
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
gray = cv2.GaussianBlur(gray, (5, 5), 0)
MOG2 history = 120, detectShadows = False, varThreshold = profile.var_threshold
morphology = OPEN x1 then CLOSE x2 with 3x3 uint8 kernel
warmup_frames = max(1, round(analysis_fps * 2.0))
stabilization_frames = max(1, round(analysis_fps * 1.5))
pixel_delta_threshold = 20
global grid = 4x4
block occupancy threshold = 30%
```

Reference semantics are exact:

```text
normal non-global frame -> becomes next reference_gray
first global-change frame -> set reference_gray=current_gray and enter stabilization
stabilizing -> compare against previous stabilization frame, then roll reference to current frame
repeated global transition -> restart full stabilization countdown
completion -> latest frame is already the new stable reference
```

Zone matching is based on contour mask intersection, not bounding-box center. Use `overlap_ratio = contour_pixels_inside_zone / contour_pixels`. Choose primary zone by largest intersection area.

For scoring, use a union mask of accepted foreground pixels to avoid double counting and normalize with:

```python
area_score = min(1.0, effective_area_ratio / max(profile.min_area_ratio * 5.0, 1e-9))
overlap_score = best_overlap_ratio if enabled_zones else 1.0
raw_score = min(1.0, area_score * overlap_score)
```

- [ ] **Step 6: Run analyzer tests and verify GREEN**

```bash
cd backend && uv run pytest tests/test_motion_analysis.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/motion_analysis.py backend/tests/test_motion_analysis.py
git commit -m "feat: add motion v2 frame analysis"
```

---

### Task 3: Add Safe Event Flush Semantics

**Files:**
- Modify: `backend/app/services/motion_detection.py`
- Test: `backend/tests/test_motion_detection.py`

**Interfaces:**
- Produces: `MotionEventStateMachine.flush(timestamp: datetime) -> list[ClosedMotionEvent]`.
- State machine tracks the last valid stable-motion timestamp so flush never fabricates duration from stabilization, missing frames, or reconnect delay.

- [ ] **Step 1: Write failing flush tests**

Add concrete tests:

```python
def test_state_machine_flush_discards_unconfirmed_candidate(): ...
def test_state_machine_flush_closes_confirmed_event_at_last_motion_time(): ...
def test_state_machine_flush_does_not_extend_to_later_pending_silence(): ...
def test_state_machine_flush_is_idempotent(): ...
```

For a confirmed event whose last valid motion is at `t=5s`, first no-motion frame is `t=6s`, and flush happens at `t=30s`, assert the event never ends after the accurate last-motion boundary. If a pending-end boundary is earlier than the recorded last-motion boundary due to an explicit state transition, choose that earlier accurate boundary.

- [ ] **Step 2: Run targeted tests and verify RED**

```bash
cd backend && uv run pytest tests/test_motion_detection.py -q
```

Expected: FAIL because explicit flush/finalization does not exist.

- [ ] **Step 3: Implement minimal flush behavior**

Track `_last_motion_at` only on stable `motion=True`. `flush(timestamp)` must:

```text
unconfirmed candidate => reset, emit []
confirmed active => emit exactly one event
end boundary => earliest accurate valid boundary from last_motion_at/pending_end_at, never flush timestamp
already reset => emit []
```

Keep `min_duration_ms`, `merge_gap_ms`, and `event_min_interval_ms` semantics unchanged.

- [ ] **Step 4: Run targeted tests and verify GREEN**

```bash
cd backend && uv run pytest tests/test_motion_detection.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/motion_detection.py backend/tests/test_motion_detection.py
git commit -m "fix: flush active motion events safely"
```

---

### Task 4: Rewire Worker Orchestration Around Analyzer + Confidence

**Files:**
- Modify: `backend/app/services/motion_worker.py`
- Test: `backend/tests/test_motion_worker.py`

**Interfaces:**
- Consumes: `MotionFrameAnalyzer` / `MotionAnalysisResult` from Task 2.
- Consumes: `MotionConfidenceTracker` / `MotionConfidenceResult` and `MotionEventStateMachine.flush()` from Tasks 1 and 3.
- Change `StatusCallback` to:

```python
StatusCallback = Callable[
    [str, MotionStream | None, datetime | None, str | None, dict[str, Any] | None],
    None,
]
```

- Diagnostic keys are exactly: `confidence`, `raw_score`, `moving_area_ratio`, `global_change_ratio`, `primary_zone_id`, `global_change`.

- [ ] **Step 1: Write failing worker/orchestration tests**

Cover:

```text
warming_up result => runtime warming_up, confidence reset, frame not snapshot-eligible
stabilizing/global-change => runtime stabilizing, frame not snapshot-eligible
normal result => runtime running with all six diagnostics
snapshot ranking prefers higher stable confidence, then raw_score
suppressed frames never replace best snapshot
```

Retain existing path-selection, scaling, and FFmpeg command tests.

- [ ] **Step 2: Run worker tests and verify RED**

```bash
cd backend && uv run pytest tests/test_motion_worker.py -q
```

Expected: FAIL on new orchestration/status behavior.

- [ ] **Step 3: Replace embedded analyzer with V2 pipeline**

Remove image-analysis implementation from `motion_worker.py`. Construct:

```python
analyzer = MotionFrameAnalyzer(self.config.sensitivity, analysis_fps=self.config.analysis_fps)
tracker = MotionConfidenceTracker(sensitivity_profile(self.config.sensitivity))
state = MotionEventStateMachine(
    min_duration_ms=self.config.min_duration_ms,
    merge_gap_ms=self.config.merge_gap_ms,
    event_min_interval_ms=self.config.event_min_interval_ms,
)
```

Per frame:

```python
analysis = analyzer.analyze(frame, self.config.zones)
suppressed = analysis.warming_up or analysis.stabilizing or analysis.global_change
confidence = tracker.update(analysis.raw_score, suppressed=suppressed)
closed = state.update(
    timestamp,
    motion=confidence.motion,
    score=confidence.confidence,
    zone_id=analysis.primary_zone_id,
)
```

This keeps temporal confidence separate from user event policy and stores V2 peak confidence in the existing `peak_score` field.

- [ ] **Step 4: Implement snapshot selection and runtime state**

Snapshot eligibility requires accepted motion evidence and excludes warm-up/global-change/stabilization. Rank candidate frames by `(confidence.confidence, analysis.raw_score)`.

Runtime precedence:

```text
warming_up -> warming_up
global_change or stabilizing -> stabilizing
otherwise -> running
```

Emit all six diagnostics with each analyzed-frame status update.

- [ ] **Step 5: Finalize confirmed events on every worker exit path**

Ensure cleanup runs for normal stream end, cancellation/settings restart, and exception/disconnect. Call `state.flush(deployment_now())`, emit returned event exactly once with the preserved best valid snapshot, then stop FFmpeg. Cancellation must still re-raise `asyncio.CancelledError` after finalization.

Do not let snapshot/event-sink failure convert a recording lifecycle into a dependency; this worker remains isolated from recorder services.

- [ ] **Step 6: Run worker/backend detector tests and verify GREEN**

```bash
cd backend && uv run pytest tests/test_motion_worker.py tests/test_motion_detection.py tests/test_motion_analysis.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/motion_worker.py backend/tests/test_motion_worker.py
git commit -m "feat: wire motion v2 worker pipeline"
```

---

### Task 5: Propagate Runtime States and Diagnostics Through Manager/API

**Files:**
- Modify: `backend/app/services/motion_manager.py`
- Modify: `backend/app/schemas/motion.py`
- Modify: `backend/app/api/motion_detection.py` only if runtime construction requires adaptation.
- Test: `backend/tests/test_motion_manager.py`
- Test: `backend/tests/test_motion_api.py`

**Interfaces:**
- Runtime state literal becomes:

```python
Literal[
    "disabled", "starting", "warming_up", "running", "stabilizing",
    "reconnecting", "error", "stopped",
]
```

- `MotionRuntimeRead` adds nullable `confidence`, `raw_score`, `moving_area_ratio`, `global_change_ratio`, `primary_zone_id`, plus `global_change: bool = False`.
- Manager status callback accepts Task 4 diagnostics and preserves useful prior diagnostics when a lifecycle-only update supplies none.

- [ ] **Step 1: Write failing schema/API tests**

Assert this runtime payload validates and is returned by `GET /api/cameras/{id}/motion-detection` when the manager reports it:

```json
{
  "state": "stabilizing",
  "stream": "sub",
  "confidence": 0.0,
  "raw_score": 0.0,
  "moving_area_ratio": 0.0,
  "global_change_ratio": 0.82,
  "primary_zone_id": null,
  "global_change": true
}
```

Also assert existing settings/event response shapes remain unchanged.

- [ ] **Step 2: Write failing manager propagation tests**

Update fake workers to call `on_status(..., diagnostics)`. Assert `manager.status(camera_id)` includes diagnostics and reconnecting/starting lifecycle transitions preserve useful stream/last-frame data without persisting diagnostics to the database.

- [ ] **Step 3: Run tests and verify RED**

```bash
cd backend && uv run pytest tests/test_motion_manager.py tests/test_motion_api.py -q
```

Expected: FAIL on callback signature/schema fields/new runtime states.

- [ ] **Step 4: Implement manager/schema/API plumbing**

Extend `_set_status()` with `diagnostics: dict[str, Any] | None = None`, initialize safe diagnostic defaults, merge only the six known diagnostic keys, and keep them in memory only.

Change new event metadata from:

```python
{"detector": "motion-v1"}
```

to:

```python
{"detector": "motion-v2"}
```

Do not add database columns or migration files.

- [ ] **Step 5: Run manager/API tests and verify GREEN**

```bash
cd backend && uv run pytest tests/test_motion_manager.py tests/test_motion_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/motion_manager.py backend/app/schemas/motion.py backend/app/api/motion_detection.py backend/tests/test_motion_manager.py backend/tests/test_motion_api.py
git commit -m "feat: expose motion v2 runtime diagnostics"
```

---

### Task 6: Add Restrained Motion V2 Runtime UI

**Files:**
- Modify: `frontend/src/MotionDetectionPanel.vue`
- Test: existing frontend test covering `MotionDetectionPanel.vue`; if absent, create `frontend/src/MotionDetectionPanel.test.ts`.

**Interfaces:**
- Extend frontend `MotionRuntime.state` with `warming_up | stabilizing`.
- Add the six diagnostics from Task 5 to the frontend runtime type.
- Do not add controls for internal thresholds.

- [ ] **Step 1: Write failing frontend behavior tests**

Cover:

```text
warming_up => 背景学习中
stabilizing => 画面稳定中
running => 检测中
confidence 0.72 => 置信度 72%
global_change true => 画面变化 全局变化抑制
primary_zone_id matching zone => 活动区域 <zone name>
primary_zone_id null => 活动区域 整个画面
```

Assert existing controls remain present and no user-facing controls/labels expose `min_zone_overlap_ratio`, `global_change_ratio`, `enter_confidence`, or `exit_confidence`.

- [ ] **Step 2: Run frontend tests and verify RED**

Try targeted execution first:

```bash
cd frontend && npm test -- MotionDetectionPanel
```

If the repository runner does not support that filter, run `npm test`. Expected: FAIL because the new states/diagnostics are missing.

- [ ] **Step 3: Implement compact diagnostics UI**

Keep the existing panel hierarchy. Add a restrained read-only summary near the runtime strip:

```text
状态      背景学习中 / 检测中 / 画面稳定中
置信度    -- / NN%
活动区域  整个画面 / zone name
画面变化  正常 / 全局变化抑制
最近帧    HH:mm:ss
```

Use subdued Protect-like styling. `warming_up` and `stabilizing` use warning/yellow indicators, never error red. Preserve the existing no-enabled-zone explanation and all user controls.

- [ ] **Step 4: Run frontend tests and build**

```bash
cd frontend && npm test && npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/MotionDetectionPanel.vue frontend/src/MotionDetectionPanel.test.ts
git commit -m "feat: show motion v2 runtime diagnostics"
```

If an existing test file is modified instead of creating `MotionDetectionPanel.test.ts`, stage that actual path.

---

### Task 7: End-to-End Regression and Failure-Isolation Coverage

**Files:**
- Modify tests as needed: `backend/tests/test_motion_worker.py`, `backend/tests/test_motion_manager.py`, `backend/tests/test_motion_api.py`, `backend/tests/test_motion_detection.py`, `backend/tests/test_motion_analysis.py`.
- Production code changes only for the smallest correction revealed by a failing behavior test.

**Interfaces:**
- Verifies the complete V2 contract from frame evidence through stable motion, event finalization, API diagnostics, and failure isolation.

- [ ] **Step 1: Add event-continuity regression across global-change suppression**

Exercise:

```text
stable motion active -> global change/stabilization -> real motion resumes inside merge_gap
```

Assert the event policy keeps one playback anchor, suppressed frames contribute no peak score, and suppressed frames cannot replace the snapshot.

- [ ] **Step 2: Add disconnect/restart flush regression**

Simulate confirmed active motion followed by cancellation/disconnect. Assert exactly one event is emitted, end time is the last accurate valid-motion boundary, and replacement worker/analyzer starts from fresh warm-up rather than extending the previous event.

- [ ] **Step 3: Add recording-isolation regression**

At the manager/service boundary, force motion-worker analysis failure and assert runtime proceeds through reconnect/error supervision without invoking or importing recording-worker stop/restart behavior. Preserve the existing independent service boundary.

- [ ] **Step 4: Run complete backend verification**

```bash
cd backend && uv run python -m compileall app && uv run pytest -q
```

Expected: all backend tests PASS.

- [ ] **Step 5: Run complete frontend verification**

```bash
cd frontend && npm test && npm run build
```

Expected: all frontend tests PASS and production build succeeds.

- [ ] **Step 6: Commit final regression coverage/fixes**

```bash
git add backend frontend/src
# commit only paths actually changed
git commit -m "test: cover motion v2 regressions"
```

Skip this commit when Task 7 produces no changes.

---

### Task 8: PR Verification, Self-Review, and Merge

**Files:**
- No planned production-file changes.

**Interfaces:**
- Apply repository `AGENTS.md`: one PR CI, self-review, merge directly if green and no blocker; do not wait for a second `main` CI by default.

- [ ] **Step 1: Review the full implementation diff against the spec**

Verify:

```text
no AI/recognition scope slipped in
no new DB threshold config or migration exists
no-zone semantics remain full-frame
warm-up/global-change/stabilization frames cannot become snapshots
rolling global-change reference converges instead of looping
large local objects do not trip global-change solely on area
small zones use zone area thresholds
primary zone uses largest real intersection
confidence uses approved evidence weighting and remains separate from event policy
flush cannot duplicate events or fabricate duration
runtime diagnostics are transient only
recording lifecycle remains independent
deployment entry remains git pull && ./deploy.sh
```

- [ ] **Step 2: Open one implementation PR to `main`**

Suggested title:

```text
feat: add motion detection v2
```

Summarize algorithm changes, runtime UI, compatibility/no migration, and test coverage.

- [ ] **Step 3: Run the single PR CI**

For this mixed backend/frontend change, expect change detection, backend tests, frontend tests/build, and Docker smoke according to current workflow gating.

- [ ] **Step 4: Self-review the complete PR diff**

Check detector state transitions, rolling global reference, cancellation/flush ordering, callback compatibility, snapshot eligibility, API backward compatibility, and recording isolation. Fix blocker-level findings and rerun naturally failed CI if needed.

- [ ] **Step 5: Merge directly when green and blocker-free**

Do not wait for a second post-merge `main` CI unless the merge itself introduces extra code/conflict/concurrent changes or a concrete reason requires re-verification.
