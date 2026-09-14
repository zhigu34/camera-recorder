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
- Existing frontend test file that covers source/behavior contracts for `MotionDetectionPanel.vue` (if none exists, create `frontend/src/MotionDetectionPanel.test.ts`) — runtime-label and diagnostics rendering tests.

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

Add tests that assert the exact profile ordering and temporal behavior:

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


def test_confidence_tracker_requires_accumulation_and_uses_hysteresis() -> None:
    tracker = MotionConfidenceTracker(sensitivity_profile("medium"))

    first = tracker.update(1.0)
    assert first.motion is False
    assert 0.0 < first.confidence < 0.65

    result = first
    for _ in range(8):
        result = tracker.update(1.0)
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

Run:

```bash
cd backend && uv run pytest tests/test_motion_detection.py -q
```

Expected: FAIL because the expanded profile fields and `MotionConfidenceTracker` do not yet exist.

- [ ] **Step 3: Implement exact internal profiles and confidence tracker**

Use these initial values:

```python
_PROFILES = {
    "low": SensitivityProfile(
        var_threshold=32,
        min_area_ratio=0.012,
        min_zone_overlap_ratio=0.35,
        global_change_ratio=0.50,
        global_block_ratio=0.75,
        confidence_gain=0.12,
        confidence_decay=0.18,
        enter_confidence=0.75,
        exit_confidence=0.20,
    ),
    "medium": SensitivityProfile(
        var_threshold=24,
        min_area_ratio=0.006,
        min_zone_overlap_ratio=0.25,
        global_change_ratio=0.60,
        global_block_ratio=0.75,
        confidence_gain=0.18,
        confidence_decay=0.14,
        enter_confidence=0.65,
        exit_confidence=0.20,
    ),
    "high": SensitivityProfile(
        var_threshold=16,
        min_area_ratio=0.0025,
        min_zone_overlap_ratio=0.15,
        global_change_ratio=0.70,
        global_block_ratio=0.75,
        confidence_gain=0.25,
        confidence_decay=0.10,
        enter_confidence=0.55,
        exit_confidence=0.15,
    ),
}
```

Implement `MotionConfidenceTracker.update()` so positive `raw_score` adds `raw_score * confidence_gain`, zero score subtracts `confidence_decay`, confidence is clamped to `[0,1]`, and state changes use enter/exit hysteresis. `suppressed=True` must reset confidence and stable motion to zero/false.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run:

```bash
cd backend && uv run pytest tests/test_motion_detection.py -q
```

Expected: PASS for new profile/confidence tests and all pre-existing state-machine tests.

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
- Modify: `backend/app/services/motion_detection.py` only if a shared typed profile import needs to move; avoid circular imports.

**Interfaces:**
- Consumes: `SensitivityProfile` from Task 1.
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
- Analyzer internally caches rasterized enabled-zone masks for the first observed frame dimensions. Worker recreation remains the cache invalidation mechanism.

- [ ] **Step 1: Write failing warm-up and normal-motion tests**

Use deterministic 360x640 black frames and white rectangles. Add helpers that feed exactly `round(fps * 2.0)` warm-up frames. Assert all warm-up results have `warming_up=True`, `raw_score=0`, no primary zone, and that a post-warm-up local rectangle yields positive raw score.

- [ ] **Step 2: Write failing global-change/stabilization tests**

Cover all of these cases:

```text
full-frame black -> full-frame white => global_change=True, raw_score=0
stabilization frames => stabilizing=True, raw_score=0
second whole-frame transition during stabilization => stabilization window restarts
post-stabilization local rectangle => raw_score>0
large local rectangle occupying only part of the 4x4 grid => global_change=False
```

Use a per-pixel absolute-delta threshold of 20 and a 4x4 changed-block distribution check. A block is considered changed when at least 25% of its pixels exceed the delta threshold; keep this constant internal and test it directly.

- [ ] **Step 3: Write failing zone-overlap/effective-area tests**

Cover:

```text
no enabled zones => full-frame mode, primary_zone_id=None
center outside zone but >= overlap threshold => accepted
small edge touch below overlap threshold => rejected
small zone + valid local motion => accepted using zone area, not whole-frame area
multi-zone hit => primary zone is largest actual intersection area
```

The accepted motion area for a zone must be based on foreground pixels actually inside that zone, and minimum area pixels must be `zone_area_pixels * profile.min_area_ratio`.

- [ ] **Step 4: Run analyzer tests and verify RED**

Run:

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
block_changed if >=25% pixels in that block exceed pixel delta
global change if changed_pixel_ratio >= profile.global_change_ratio AND changed_block_ratio >= profile.global_block_ratio
```

Reference-frame rule: compare against the last accepted stable grayscale frame; on a detected global change, update/rebase the reference during stabilization so the analyzer cannot remain permanently anchored to the pre-transition scene. Another global change while stabilizing restarts the stabilization frame counter.

For scoring, use accepted foreground union pixels to avoid double counting and normalize with:

```python
area_score = min(1.0, effective_area_ratio / max(profile.min_area_ratio * 5.0, 1e-9))
overlap_score = best_overlap_ratio if enabled_zones else 1.0
raw_score = min(1.0, area_score * overlap_score)
```

- [ ] **Step 6: Run analyzer tests and verify GREEN**

Run:

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
- State machine must track the last valid stable-motion timestamp so flush does not fabricate duration from later warm-up/stabilization/disconnect time.

- [ ] **Step 1: Write failing flush tests**

Add tests for:

```python
def test_state_machine_flush_discards_unconfirmed_candidate(): ...
def test_state_machine_flush_closes_confirmed_event_at_last_motion_time(): ...
def test_state_machine_flush_uses_pending_end_when_present(): ...
def test_state_machine_flush_is_idempotent(): ...
```

For a confirmed event that last saw valid motion at `t=5s` and is flushed at `t=30s`, assert `ended_at == t=5s`, not `t=30s`.

- [ ] **Step 2: Run targeted tests and verify RED**

```bash
cd backend && uv run pytest tests/test_motion_detection.py -q
```

Expected: FAIL because `flush()` and last-valid-motion tracking do not exist.

- [ ] **Step 3: Implement minimal flush behavior**

Track `_last_motion_at` only on stable `motion=True` updates. `flush(timestamp)` must:

```text
candidate only => reset, emit []
confirmed active => emit exactly one ClosedMotionEvent using pending_end_at if present, otherwise last_motion_at, otherwise started_at
already reset => emit []
```

Do not change the configured `min_duration_ms`, `merge_gap_ms`, or `event_min_interval_ms` semantics.

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
- Change `StatusCallback` to carry diagnostics explicitly:

```python
StatusCallback = Callable[
    [str, MotionStream | None, datetime | None, str | None, dict[str, Any] | None],
    None,
]
```

- Diagnostic payload keys are exactly: `confidence`, `raw_score`, `moving_area_ratio`, `global_change_ratio`, `primary_zone_id`, `global_change`.

- [ ] **Step 1: Write failing orchestration tests**

Add worker-level tests using injected/fake analyzer/state dependencies where practical, or extract a small pure helper for translating `MotionAnalysisResult + MotionConfidenceResult` into runtime state/diagnostics. Cover:

```text
warming_up analysis => runtime state warming_up, confidence reset, no snapshot candidate
stabilizing/global_change => runtime state stabilizing, no snapshot candidate
normal frame => runtime state running with diagnostics
strongest valid frame prefers higher confidence, then raw_score
suppressed frames never replace best snapshot
```

Preserve existing tests for path selection, scaled dimensions, and FFmpeg command construction.

- [ ] **Step 2: Run worker tests and verify RED**

```bash
cd backend && uv run pytest tests/test_motion_worker.py -q
```

Expected: FAIL on the new runtime/diagnostic behavior.

- [ ] **Step 3: Replace embedded `MotionFrameAnalyzer` implementation with imports from `motion_analysis.py`**

Remove image-analysis code from `motion_worker.py`. Construct:

```python
analyzer = MotionFrameAnalyzer(self.config.sensitivity, analysis_fps=self.config.analysis_fps)
tracker = MotionConfidenceTracker(sensitivity_profile(self.config.sensitivity))
state = MotionEventStateMachine(...)
```

For each frame:

```text
analysis = analyzer.analyze(frame, zones)
suppressed = analysis.warming_up or analysis.stabilizing or analysis.global_change
confidence = tracker.update(analysis.raw_score, suppressed=suppressed)
stable motion + analysis.primary_zone_id -> MotionEventStateMachine.update(...)
```

Use stable confidence as the event score input so `peak_score` remains meaningful under V2.

- [ ] **Step 4: Implement snapshot selection and runtime callback**

A frame is snapshot-eligible only when it contributes valid motion evidence and is not warm-up/global-change/stabilization. Compare candidate keys as `(confidence.confidence, analysis.raw_score)`.

Runtime state precedence per analyzed frame:

```text
warming_up -> warming_up
stabilizing or global_change -> stabilizing
otherwise -> running
```

Emit the six diagnostic fields every analyzed frame.

- [ ] **Step 5: Flush confirmed events in `finally` before stopping FFmpeg**

On normal stop, cancellation, settings restart, or stream failure, call `state.flush(deployment_now())` and emit returned events with the current best valid snapshot exactly once. If no event is active, do nothing. Do not swallow cancellation; flush first, then re-raise `asyncio.CancelledError`.

- [ ] **Step 6: Run worker tests and verify GREEN**

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
- Modify: `backend/app/api/motion_detection.py` only if runtime construction needs adaptation.
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
- Manager status callback accepts the Task 4 diagnostics dict and retains prior diagnostics when a lifecycle-only update does not supply new values.

- [ ] **Step 1: Write failing schema/API tests**

Assert a runtime payload containing:

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

validates and is returned by `GET /api/cameras/{id}/motion-detection` when the manager reports it.

- [ ] **Step 2: Write failing manager propagation tests**

Update fake workers to call `on_status(..., diagnostics)` and assert `manager.status(camera_id)` contains diagnostics while reconnecting lifecycle changes preserve useful `stream`/last-frame context.

- [ ] **Step 3: Run tests and verify RED**

```bash
cd backend && uv run pytest tests/test_motion_manager.py tests/test_motion_api.py -q
```

Expected: FAIL on callback signature/schema fields/new runtime states.

- [ ] **Step 4: Implement manager/schema/API plumbing**

Extend `_set_status()` with `diagnostics: dict[str, Any] | None = None`, initialize safe default diagnostic values, merge only known keys, and keep runtime data in memory only.

Change persisted event metadata in `_default_event_sink()` from:

```python
{"detector": "motion-v1"}
```

to:

```python
{"detector": "motion-v2"}
```

Do not add a migration or settings fields.

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
- Test: existing frontend test covering `MotionDetectionPanel.vue`; if none exists, create `frontend/src/MotionDetectionPanel.test.ts`.

**Interfaces:**
- Extend frontend `MotionRuntime.state` with `warming_up | stabilizing`.
- Extend frontend runtime type with the six diagnostics from Task 5.
- Do not add controls for internal thresholds.

- [ ] **Step 1: Write failing frontend behavior tests**

Cover these user-visible mappings:

```text
warming_up => 背景学习中
stabilizing => 画面稳定中
running => 检测中
confidence 0.72 => 置信度 72%
global_change true => 画面变化 全局变化抑制
primary_zone_id matching zone => 活动区域 <zone name>
primary_zone_id null => 活动区域 整个画面
```

Also assert the existing controls are still present and there are no controls/labels exposing `min_zone_overlap_ratio`, `global_change_ratio`, `enter_confidence`, or `exit_confidence`.

- [ ] **Step 2: Run frontend tests and verify RED**

Run the repository's existing frontend test command, targeting the new test where supported:

```bash
cd frontend && npm test -- MotionDetectionPanel
```

If the test runner does not support name filtering, run:

```bash
cd frontend && npm test
```

Expected: FAIL because the new states/diagnostics UI is missing.

- [ ] **Step 3: Implement runtime labels and diagnostics strip**

Keep the existing panel hierarchy. Add only a compact diagnostic summary near the current runtime strip. Suggested visible fields:

```text
状态      背景学习中 / 检测中 / 画面稳定中
置信度    -- / NN%
活动区域  整个画面 / zone name
画面变化  正常 / 全局变化抑制
最近帧    HH:mm:ss
```

Use subdued styling consistent with the existing Protect-like dense UI. `warming_up` and `stabilizing` should use the warning/yellow runtime indicator, not error red.

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

If an existing test file was modified instead of creating `MotionDetectionPanel.test.ts`, add that actual path to the commit.

---

### Task 7: End-to-End Regression and Failure-Isolation Coverage

**Files:**
- Modify tests only as needed: `backend/tests/test_motion_worker.py`, `backend/tests/test_motion_manager.py`, `backend/tests/test_motion_api.py`, `backend/tests/test_motion_detection.py`, `backend/tests/test_motion_analysis.py`.
- No production refactor unless a failing behavior requires the smallest correction.

**Interfaces:**
- Verifies the complete V2 contract from frame evidence through runtime/event persistence boundaries.

- [ ] **Step 1: Add regression test for event continuity across global-change suppression**

Create a deterministic state sequence showing:

```text
stable motion active -> global change suppression -> real motion resumes within merge_gap
```

Assert there is still one event anchor, not two, and the suppressed frames do not increase peak score or snapshot quality.

- [ ] **Step 2: Add regression test for disconnect/restart flush**

Simulate a confirmed active event followed by worker cancellation/disconnect. Assert exactly one event is emitted, its end time is the last valid stable-motion time, and a reconnect starts a fresh warm-up rather than extending the old event.

- [ ] **Step 3: Add regression test proving motion failure does not touch recording lifecycle**

Keep this at the manager/service boundary: a motion worker failure must move runtime to `reconnecting`/`error` without invoking recording stop/restart code. If there is no direct recording dependency in the manager, assert the module/service graph remains independent and no recording service callback is introduced.

- [ ] **Step 4: Run the complete backend suite**

```bash
cd backend && uv run python -m compileall app && uv run pytest -q
```

Expected: all backend tests PASS.

- [ ] **Step 5: Run the complete frontend suite**

```bash
cd frontend && npm test && npm run build
```

Expected: all frontend tests PASS and production build succeeds.

- [ ] **Step 6: Commit regression coverage/final fixes**

```bash
git add backend/tests frontend/src
# add any minimal production files changed by the final regression pass
git commit -m "test: cover motion v2 regressions"
```

Skip this commit if Task 7 requires no file changes.

---

### Task 8: PR Verification, Self-Review, and Merge

**Files:**
- No planned production-file changes.

**Interfaces:**
- Applies the repository workflow in `AGENTS.md`: one PR CI, self-review, merge directly if green and no blocker; no second `main` CI wait by default.

- [ ] **Step 1: Review full branch diff against the spec**

Verify specifically:

```text
no AI/recognition scope slipped in
no new DB migration/config controls were added
no-zone semantics remain full-frame
warm-up/global-change/stabilization frames cannot become snapshots
large local objects do not trip global-change solely on area
small zones use zone area thresholds
primary zone uses largest intersection
confidence/hysteresis is separate from event policy
flush cannot duplicate events or fabricate end duration
runtime diagnostics are transient only
recording code/lifecycle remains untouched by detector failures
deployment entry remains git pull && ./deploy.sh
```

- [ ] **Step 2: Open a PR from the implementation branch to `main`**

Use a title such as:

```text
feat: add motion detection v2
```

PR body should summarize algorithm changes, runtime UI, compatibility/no migration, and testing.

- [ ] **Step 3: Let the single PR CI run**

Expected paths for this mixed backend/frontend change: changes detection, backend tests, frontend tests/build, and Docker smoke all pass according to current workflow gating.

- [ ] **Step 4: Self-review the PR diff**

Check for blocker-level correctness issues, especially detector state transitions, cancellation/flush ordering, callback compatibility, snapshot eligibility, and accidental settings/API breaking changes.

- [ ] **Step 5: Merge directly when CI is green and self-review has no blocker**

Do not wait for a second post-merge `main` CI unless the merge itself introduces extra code/conflict/concurrent changes or there is a concrete reason to re-verify.
