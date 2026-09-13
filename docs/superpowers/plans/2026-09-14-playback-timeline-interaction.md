# Playback Timeline Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the playback position obvious and draggable, add non-destructive hover time preview, preserve viewport pan/zoom, and add a two-handle export range-selection mode without changing manual media-start semantics.

**Architecture:** Keep `PlaybackTimelineV3.vue` as the single visual timeline component, but replace overlapping drag booleans with one explicit interaction state. The component owns visual wall-clock cursor/range state and emits intent; `PlaybackWorkspace.vue` remains the only owner of actual media seek/play and export business. Background pan changes only viewport position, never playback time. Range selection never calls media APIs.

**Tech Stack:** Vue 3, TypeScript, Pointer Events, Vitest, existing playback timeline utilities and Element Plus workspace controls.

**Spec:** `docs/superpowers/specs/2026-09-14-playback-timeline-interaction-design.md`

## Global Constraints

- Entering playback/deep-link still restores context only; it must not start media.
- Existing explicit timeline/event actions may start playback when they target a valid recording.
- A visible playhead is not proof that media is playing; it represents the selected/current wall-clock position.
- Clicking or dragging into a gap may move the visual wall-clock cursor but must not open, seek, or play another recording.
- Do not snap gap positions to the nearest recording.
- Dragging the timeline background pans the viewport only; it must not move the playhead and must not emit a seek on pointerup.
- 24h view remains non-pannable; 6h/1h/15m remain pannable.
- Wheel zoom remains anchored under the pointer.
- Playhead, range handles, range body, and pan background have explicit event priority and cannot respond to the same pointer sequence.
- Range selection is independent of playback; no range event may call player `open` or `play`.
- Preserve strict player 16:9 and existing playback source behavior; this plan touches timeline/workspace interaction only.

---

### Task 1: Timeline range and interaction utility contracts

**Files:**
- Modify: `frontend/src/utils/playbackTimelineV3.ts`
- Modify: `frontend/src/playbackTimelineV3.test.ts`

**Interfaces:**
- `TimelineSelectionRange { start: number; end: number }`.
- `normalizeTimelineRange(start, end, minDuration?)` clamps to `[0,86400]` and orders endpoints.
- `resizeTimelineRange(range, edge, target, minDuration?)`.
- `moveTimelineRange(range, deltaSeconds)` preserves duration while clamping at day boundaries.
- Keep existing `timeAtTrackPointer` and `rangePercent` as the coordinate source of truth.

- [ ] Add failing tests for reversed endpoints, day-boundary clamp, minimum duration, left/right resize, and whole-range movement at both day edges.
- [ ] Verify RED before implementation.
- [ ] Implement the smallest pure helpers needed by the component.
- [ ] Verify the focused utility tests GREEN.

### Task 2: Replace drag booleans with an explicit interaction state

**Files:**
- Modify: `frontend/src/PlaybackTimelineV3.vue`
- Create: `frontend/src/playbackTimelineInteractionSemantics.test.ts`

**Interfaces:**
- Internal state type: `idle | pan | playhead-drag | range-start-drag | range-end-drag | range-move`.
- Existing final `seek` event remains supported for compatibility.
- Add `seek-preview` for throttled valid-recording drag preview if used.
- Add `range-change` and `range-commit`.

- [ ] Add failing component-source semantic tests proving there is one interaction state, independent playhead hit target, and no `pointer-events:none` on the hit target.
- [ ] Verify RED.
- [ ] Refactor current background drag code into `pan` state without changing zoom math.
- [ ] Remove the current behavior that assigns the cursor to viewport center during pan and emits seek at pan end.
- [ ] Keep click suppression/movement threshold so pan pointerup cannot fall through to click seek.
- [ ] Verify existing timeline tests and new semantics tests GREEN.

### Task 3: Visible draggable playhead and hover preview

**Files:**
- Modify: `frontend/src/PlaybackTimelineV3.vue`
- Modify: `frontend/src/playbackTimelineInteractionSemantics.test.ts`

**Behavior:**
- Render a clear playhead line, `HH:mm:ss` bubble, and a separate larger round/handle hit target.
- `pointerdown` on the hit target starts `playhead-drag` and uses pointer capture.
- While dragging, update `cursorSeconds` continuously.
- If target has recording coverage, optionally emit throttled `seek-preview`; final pointerup emits `seek` once.
- If target is a gap, visual cursor stays there and final intent is still distinguishable as a gap by workspace logic; media does not move.
- Hover over the main track renders a low-emphasis preview line/time bubble and disappears on leave; hover never emits seek.

- [ ] Add failing tests/semantic assertions for playhead time label, dedicated hit target, hover handlers, and gap-capable cursor update.
- [ ] Verify RED.
- [ ] Implement playhead drag and hover preview.
- [ ] Ensure `watch(activeWallSeconds)` continues syncing the visual playhead when actual playback time changes, except active pointer drag must not be overwritten mid-gesture.
- [ ] Ensure pan never moves the playhead.
- [ ] Verify tests/build GREEN.

### Task 4: Workspace gap semantics and explicit seek behavior

**Files:**
- Modify: `frontend/src/PlaybackWorkspace.vue`
- Modify: `frontend/src/utils/playbackWorkspaceNavigation.ts` only if a pure helper is needed.
- Modify: `frontend/src/playbackWorkspaceNavigation.test.ts`
- Create: `frontend/src/playbackTimelineWorkspaceSemantics.test.ts`

**Behavior:**
- Valid timeline click/drag commit remains an explicit user playback action.
- Same-recording seek may seek/play as today; switching recording may explicitly open it as today.
- Gap commit shows “该时间没有可播放录像” but does not open/play/seek media.
- The timeline component's local cursor is allowed to remain at the gap time even though `activeWallSeconds` continues to represent actual media time.
- Player `timeupdate` later re-synchronizes the playhead when media is actually playing again.

- [ ] Extend failing tests to distinguish gap intent from valid seek and protect manual page-load behavior.
- [ ] Verify RED where applicable.
- [ ] Implement only workspace changes needed for the new event contract; do not make gap actions update active recording or route.
- [ ] Verify tests GREEN.

### Task 5: Add range-selection props and two-handle rendering

**Files:**
- Modify: `frontend/src/PlaybackTimelineV3.vue`
- Modify: `frontend/src/playbackTimelineInteractionSemantics.test.ts`

**Component contract:**
- Props: `rangeSelectEnabled?: boolean`, `selectedRange?: TimelineSelectionRange | null`.
- Emits: `range-change`, `range-commit`.
- Workspace remains source of truth for committed export range; component may maintain gesture-local range while dragging.

**Behavior:**
- In range mode render selected band plus start/end handles with wall-clock labels.
- Playhead stays visible but lower visual priority.
- Handle hit targets have priority over range-body drag; range-body has priority over background pan.
- Drag start/end handle uses resize helper and preserves minimum duration.
- Drag selected band moves the whole range and clamps to the day.
- Range pointer operations never emit `seek` and never call media.
- Cancel/disable range mode returns interaction state to `idle` and restores normal playhead behavior.

- [ ] Add failing semantics tests for two handles, selected band, priority-specific pointer handlers, and no seek from range gestures.
- [ ] Verify RED.
- [ ] Implement rendering and pointer state transitions.
- [ ] Verify utility/component tests GREEN.

### Task 6: Wire export-range mode into PlaybackWorkspace

**Files:**
- Modify: `frontend/src/PlaybackWorkspace.vue`
- Use types/helpers created by the range-export implementation.
- Modify/create export workflow tests as specified by `2026-09-14-range-export.md`.

**Behavior:**
- “导出片段” toggles range mode; it does not open/play media.
- Initial range: current wall-clock position through +5 minutes, clamped to day end; if no current position, use first recording start when possible.
- Range-change updates only visual/state selection.
- Range-commit stores the final selected range.
- Camera/date changes cancel range mode and clear stale range/analyze results.
- “取消” exits range mode without changing active recording/playback.

- [ ] Write failing workflow tests for initial range, cancel behavior, camera/date reset, and no media-start side effect.
- [ ] Verify RED.
- [ ] Wire timeline props/events to workspace export state.
- [ ] Verify frontend tests/build GREEN.

### Task 7: Accessibility, visual polish and regression checks

**Files:**
- Modify: `frontend/src/PlaybackTimelineV3.vue`
- Modify: `frontend/src/styles/playback-workspace-density.css` only if cross-component styling is needed.
- Modify tests without using standalone CSS `?raw` assertions.

**Checks:**
- Playhead handle is keyboard-focusable if implemented as a control; otherwise expose meaningful ARIA text and ensure mouse/touch target is sufficiently large.
- Time labels use tabular numerals.
- Light/dark theme contrast remains clear through existing CSS variables.
- Hover is supplemental and not required for touch operation.
- Overview ruler and 24h overview remain intact.

- [ ] Add/adjust regression tests using `.vue?raw`, TypeScript helpers, or build output; do not use standalone CSS `?raw` because this repo's Vitest setup has returned empty content for that pattern.
- [ ] Run all frontend tests.
- [ ] Run `npm run build`.
- [ ] Review behavior at all four zoom levels and at 00:00/24:00 boundaries.
- [ ] Verify player still uses strict 16:9 and `object-fit: contain`.
- [ ] Verify entering playback still does not auto-start media.

### Task 8: Integration with range export and full CI

**Files:**
- Modify only if integration exposes a defect.

- [ ] Verify normal mode: click seek, playhead drag seek, hover preview, background pan, wheel zoom.
- [ ] Verify gap mode: visual cursor can enter gap; media stays unchanged.
- [ ] Verify export mode: start/end drag and range move do not seek/play.
- [ ] Verify analysis/export receives the committed range exactly once after explicit user confirmation.
- [ ] Run full backend/frontend/Docker PR CI with the range-export work.
- [ ] Review PR diff for accidental autoplay, pointer-event conflicts, or loss of existing motion event track behavior.
- [ ] Merge only after all checks are green; verify main CI after merge.
