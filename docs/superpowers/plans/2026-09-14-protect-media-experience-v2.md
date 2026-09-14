# Protect Media Experience V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify Playback, detection events, and Live Monitoring into a Protect-style media experience, add truly independent Live tile start/pause behavior, and shorten frontend-only PR CI.

**Architecture:** Keep all existing backend media APIs and recording semantics. Playback gains a custom overlay control surface around the existing `<video>` source lifecycle; Live changes from one global websocket to one websocket per user-started tile, each submitting a single slot to the existing `/ws/preview-wall` endpoint; event data/seek logic stays intact while the rail is visually simplified. CI adds one change-detection job and conditionally runs frontend/backend/docker jobs on pull requests.

**Tech Stack:** Vue 3 + TypeScript, native HTMLVideoElement APIs, Element Plus icons where appropriate, WebSocket, Vitest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-14-protect-media-experience-v2-design.md`

## Global Constraints

- Navigation/deep links must not auto-start Live or Playback media.
- A Live tile starts only after explicit user action and can be paused/resumed independently of every other tile.
- The center of a Live tile contains only the primary Start/Pause/Resume/Retry action.
- Fullscreen, settings, stream policy, and remove actions stay at the tile edge/peripheral toolbar.
- Do not change preview-wall backend protocol, recording/remux/export behavior, migrations, or database models.
- Preserve playback rates `0.5x / 1x / 1.5x / 2x / 4x` and skip intervals `5 / 10 / 15 / 20 / 25 / 30` seconds.
- Tests protect user-visible behavior, not CSS implementation details.
- Delivery is one branch, one PR, one PR CI run unless a natural failure requires a rerun.
- Deployment remains `git pull && ./deploy.sh`.

---

### Task 1: Consolidate Playback into one custom media control surface

**Files:**
- Create: `frontend/src/PlaybackMediaControls.vue`
- Modify: `frontend/src/PlaybackPlayer.vue`
- Modify: `frontend/src/PlaybackWorkspace.vue`
- Delete after migration: `frontend/src/PlaybackTransportControls.vue`
- Modify: `frontend/src/types/recordings.ts`
- Modify: `frontend/src/playbackTransport.test.ts`
- Modify: `frontend/src/manualMediaStart.test.ts`

**Interfaces:**
- `PlaybackPlayer.vue` exposes media state through events: `playing-change: [boolean]`, `muted-change: [boolean]`, `volume-change: [number]` and continues existing `timeupdate`, `ended`, `error`, `recording-change` events.
- `PlaybackPlayerHandle` adds `setVolume(volume: number): void`, `setMuted(muted: boolean): void`, `toggleFullscreen(): Promise<void>` while preserving `select`, `open`, `seek`, `play`, `pause`.
- `PlaybackMediaControls.vue` consumes `active`, `playing`, `playbackRate`, `skipSeconds`, `muted`, `volume`; emits `toggle-play`, `skip`, `update:playbackRate`, `update:skipSeconds`, `update:muted`, `update:volume`, `fullscreen`.
- Cross-recording skip remains owned by `PlaybackWorkspace.vue` through the existing `skipPlayback()` / `seekWallClock()` path.

- [ ] **Step 1: Update behavior tests before changing the player surface**

Replace brittle assertions that require the old `PlaybackTransportControls` placement with semantic source assertions. The integration section in `playbackTransport.test.ts` should verify concepts such as:

```ts
expect(playerSource).not.toContain(' controls\n')
expect(workspaceSource).toContain('<PlaybackMediaControls')
expect(workspaceSource).toContain('@skip="skipPlayback"')
expect(workspaceSource).toContain('@toggle-play="togglePlayback"')
expect(playerSource).toContain('function setVolume(')
expect(playerSource).toContain('function setMuted(')
expect(playerSource).toContain('function toggleFullscreen(')
```

Keep helper tests for the fixed rate/skip sets and wall-clock clamp because they protect real behavior. Update `manualMediaStart.test.ts` so it verifies `select()` still stages a source and the placeholder/custom play action is explicit; do not assert old global Live flags that Task 3 will remove.

- [ ] **Step 2: Implement `PlaybackMediaControls.vue`**

Use actual SVG/icon buttons rather than Unicode transport symbols. The component should have one bottom overlay row with icon-first controls and compact popovers/selects for rate/skip. Core template shape:

```vue
<div class="media-controls" :class="{ visible: forceVisible }" @pointermove="showControls">
  <button type="button" :aria-label="playing ? '暂停' : '播放'" @click="emit('toggle-play')">…</button>
  <button type="button" :disabled="!active" @click="emit('skip', -skipSeconds)">…</button>
  <button type="button" :disabled="!active" @click="emit('skip', skipSeconds)">…</button>
  <div class="media-controls-spacer" />
  <button type="button" @click="emit('update:muted', !muted)">…</button>
  <input type="range" min="0" max="1" step="0.05" :value="volume" @input="onVolume" />
  <select :value="playbackRate" @change="onRate">…</select>
  <select :value="skipSeconds" @change="onSkipInterval">…</select>
  <button type="button" aria-label="全屏" @click="emit('fullscreen')">…</button>
</div>
```

Auto-hide with a short inactivity timer only while media is playing; keep controls visible when paused or keyboard-focused. Preserve visible `:focus-visible` outlines.

- [ ] **Step 3: Extend `PlaybackPlayer.vue` with real media state and imperative controls**

Remove native `controls`. Add refs for `playing`, `muted`, and `volume`. Keep `autoplay` only for a source that was explicitly opened by `open()`; page entry still calls `select()` and therefore has no `videoSrc`.

On video events:

```ts
function handleVideoPlaying() {
  playing.value = true
  emit('playing-change', true)
  // existing playback-rate/tracker logic remains
}

function handleVideoPause() {
  playing.value = false
  emit('playing-change', false)
}
```

Add:

```ts
function setVolume(value: number) {
  const next = Math.max(0, Math.min(1, value))
  if (videoRef.value) videoRef.value.volume = next
  emit('volume-change', next)
}

function setMuted(value: boolean) {
  if (videoRef.value) videoRef.value.muted = value
  emit('muted-change', value)
}

async function toggleFullscreen() {
  const box = playerBoxRef.value
  if (!box) return
  if (document.fullscreenElement) await document.exitFullscreen()
  else await box.requestFullscreen()
}
```

Expose these methods through `defineExpose<PlaybackPlayerHandle>()` and keep the existing compatibility fallback untouched.

- [ ] **Step 4: Wire media controls in `PlaybackWorkspace.vue`**

Track `playerPlaying`, `playerMuted`, `playerVolume`. Add:

```ts
async function togglePlayback() {
  if (playerPlaying.value) {
    playerRef.value?.pause()
    return
  }
  await playerRef.value?.play().catch(() => undefined)
}
```

Render `PlaybackMediaControls` as an overlay associated with the player area and route skip/rate/interval to the existing handlers. Volume/mute/fullscreen delegate directly to `PlaybackPlayerHandle`.

- [ ] **Step 5: Run targeted Playback verification**

Run from `frontend/`:

```bash
npm test -- playbackTransport.test.ts manualMediaStart.test.ts playbackWorkspaceNavigation.test.ts
npm run build
```

Expected: all selected tests pass and `vue-tsc`/Vite build completes successfully.

- [ ] **Step 6: Commit Playback V2**

```bash
git add frontend/src/PlaybackMediaControls.vue frontend/src/PlaybackPlayer.vue frontend/src/PlaybackWorkspace.vue frontend/src/types/recordings.ts frontend/src/playbackTransport.test.ts frontend/src/manualMediaStart.test.ts frontend/src/PlaybackTransportControls.vue
git commit -m "feat: unify playback media controls"
```

---

### Task 2: Simplify the Playback detection event rail

**Files:**
- Modify: `frontend/src/PlaybackEventFeed.vue`
- Modify only if behavior requires it: `frontend/src/motionEventFeed.test.ts`
- Modify: `frontend/src/playbackEventRailLayout.test.ts`

**Interfaces:**
- Preserve `emit('seek', motionEventSeekTarget(event))` exactly as the event-to-playback contract.
- Preserve snapshot URL/error handling and active-event matching against `activeWallSeconds`.

- [ ] **Step 1: Adjust event rail assertions to behavior and structure**

Keep assertions that the rail is internally scrollable and that events remain buttons which emit seek. Remove assertions tied to decorative borders/card chrome. Add a semantic source assertion that the event item still calls `openEvent(event)` and `openEvent` still emits `motionEventSeekTarget(event)`.

- [ ] **Step 2: Refactor `PlaybackEventFeed.vue` markup into a compact feed row**

Keep the existing thumbnail and metadata calculations. Change each item from a visually boxed card to a low-chrome row:

```vue
<button class="event-row" :class="{ active: isActive(event) }" @click="openEvent(event)">
  <div class="event-thumb">…</div>
  <div class="event-meta">
    <div class="event-primary"><strong>移动</strong><time>{{ clockLabel(event.started_at) }}</time></div>
    <div class="event-secondary"><span>{{ motionEventZoneLabel(event, zones) }}</span><span>{{ durationLabel(event) }}</span></div>
  </div>
  <span class="event-active-mark" aria-hidden="true"></span>
</button>
```

Remove the redundant “点击从事件前 2 秒播放” copy and reduce disabled future-filter prominence. Do not invent person/vehicle data.

- [ ] **Step 3: Run event-feed verification**

```bash
npm test -- motionEventFeed.test.ts playbackEventRailLayout.test.ts
npm run build
```

Expected: event target semantics and rail layout tests pass; frontend build succeeds.

- [ ] **Step 4: Commit event rail V2**

```bash
git add frontend/src/PlaybackEventFeed.vue frontend/src/motionEventFeed.test.ts frontend/src/playbackEventRailLayout.test.ts
git commit -m "feat: refine playback event feed"
```

---

### Task 3: Convert Live Monitoring to independent per-tile start/pause connections

**Files:**
- Modify: `frontend/src/PreviewView.vue`
- Create: `frontend/src/utils/previewTileState.ts`
- Create: `frontend/src/previewTileState.test.ts`
- Modify: `frontend/src/manualMediaStart.test.ts`
- Modify: `frontend/src/previewActionSemantics.test.ts`

**Interfaces:**
- `previewTileState.ts` defines:

```ts
export type PreviewTileState = 'idle' | 'connecting' | 'playing' | 'paused' | 'retrying' | 'error'
export function tilePrimaryAction(state: PreviewTileState): 'start' | 'pause' | 'resume' | 'retry'
export function shouldResumeAfterVisibility(startedByUser: boolean, state: PreviewTileState): boolean
```

- Each `WallSlot` owns `state`, `startedByUser`, `socket`, `socketGeneration`, `reconnectTimer` in addition to existing camera/stream/frame fields. Runtime socket/timer fields are never serialized.
- `connectSlot(index)` creates one websocket and sends exactly one slot in `slots: [{ index, camera_id, stream }]`.
- `pauseSlot(index)` closes only that slot connection and marks `paused`.

- [ ] **Step 1: Add small pure-state tests**

Create `previewTileState.test.ts` with behavior such as:

```ts
expect(tilePrimaryAction('idle')).toBe('start')
expect(tilePrimaryAction('playing')).toBe('pause')
expect(tilePrimaryAction('paused')).toBe('resume')
expect(tilePrimaryAction('error')).toBe('retry')
expect(shouldResumeAfterVisibility(false, 'paused')).toBe(false)
expect(shouldResumeAfterVisibility(true, 'playing')).toBe(true)
```

Update `manualMediaStart.test.ts` so Live assertions verify the absence of mount-time `connectSlot(...)` calls and the presence of an explicit `startSlot(index)` path rather than the removed `wallStarted/wallPaused` globals.

Update `previewActionSemantics.test.ts` to assert central primary controls call `toggleSlotPlayback(index)` and peripheral controls keep playback/settings/fullscreen separate.

- [ ] **Step 2: Replace global Live connection state with slot-owned state**

Remove global `wallPaused`, `wallStarted`, `connectionState`, `socket`, `socketGeneration`, `reconnectTimer`, and `connectWall()`.

Use a runtime-capable slot structure conceptually equivalent to:

```ts
interface WallSlot {
  cameraId: number | null
  stream: PreviewStream
  activeStream: ActivePreviewStream | null
  frameUrl: string
  loaded: boolean
  failed: boolean
  error: string
  state: PreviewTileState
  startedByUser: boolean
  socket: WebSocket | null
  socketGeneration: number
  reconnectTimer: number | null
}
```

`persistWall()` must continue serializing only `{ cameraId, stream }`.

- [ ] **Step 3: Implement one websocket per active tile**

`connectSlot(index)` must:

1. refuse to run for an empty/unmounted/hidden tile;
2. close only that slot's prior socket;
3. create `new WebSocket(wsUrl())`;
4. set `state = 'connecting'`;
5. on open send the existing payload with one slot only:

```ts
ws.send(JSON.stringify({
  fps: previewProfile.value.fps,
  width: previewProfile.value.width,
  slots: [{ index, camera_id: slot.cameraId, stream: slot.stream }],
}))
```

6. route binary frames only to this index;
7. map `slot_ready`/`slot_fallback` to `playing`, `slot_error` to `error`;
8. schedule reconnect only for that slot when it was started by the user and is not explicitly paused.

- [ ] **Step 4: Implement per-tile primary actions**

Add:

```ts
function startSlot(index: number) {
  const slot = slots.value[index]
  if (!slot || slot.cameraId === null) return
  slot.startedByUser = true
  connectSlot(index)
}

function pauseSlot(index: number) {
  const slot = slots.value[index]
  if (!slot) return
  closeSlotSocket(slot)
  slot.state = 'paused'
}

function toggleSlotPlayback(index: number) {
  const slot = slots.value[index]
  const action = tilePrimaryAction(slot.state)
  if (action === 'pause') pauseSlot(index)
  else startSlot(index)
}
```

A pause must close the websocket so backend RTSP/JPEG work stops for that tile.

- [ ] **Step 5: Make configuration mutations affect only their own tile**

- `setStream(index, stream)`: if tile is user-started and active, reconnect only `index`; otherwise only persist the policy.
- `clearSlot(index)`: close/revoke/reset only `index`.
- `assignCamera(index, id)`: stop the old content in that destination; assignment does not auto-start the new camera.
- moving an already-assigned camera clears/stops its old slot without touching unrelated slots.
- `changeLayout(value)`: for indexes hidden by the new layout, close their sockets immediately; do not start newly visible slots.
- `autoFill()`: assign only; never connect.

- [ ] **Step 6: Rebuild tile chrome with one central control**

The center markup must contain only the primary action button:

```vue
<button class="tile-primary-action" type="button" @click.stop="toggleSlotPlayback(index)">
  <span class="tile-primary-icon">…</span>
  <span>{{ primaryActionLabel(slot.state) }}</span>
</button>
```

Place camera name/REC top-left, stream status top-right, and secondary toolbar at the lower/right edge on hover. Fullscreen/settings/stream/remove must not be descendants of `.tile-primary-action` or the central overlay container.

Desktop: peripheral buttons can be individual icon buttons. Mobile: collapse secondary actions into an edge `…` menu.

- [ ] **Step 7: Preserve visibility resource safety**

On `document.hidden`, close sockets for currently user-started active tiles but record that they were active. On visible, reconnect only tiles that were explicitly started before hiding; never connect idle/unstarted tiles.

- [ ] **Step 8: Run Live targeted verification**

```bash
npm test -- previewTileState.test.ts manualMediaStart.test.ts previewActionSemantics.test.ts
npm run build
```

Expected: targeted tests pass and TypeScript/build succeeds.

- [ ] **Step 9: Commit independent Live tile lifecycle**

```bash
git add frontend/src/PreviewView.vue frontend/src/utils/previewTileState.ts frontend/src/previewTileState.test.ts frontend/src/manualMediaStart.test.ts frontend/src/previewActionSemantics.test.ts
git commit -m "feat: add independent live tile controls"
```

---

### Task 4: Gate PR CI by changed paths

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Always-present job `changes` exposes outputs `frontend`, `backend`, `docker`.
- On `push` to `main`, all three outputs resolve true so repository-health CI remains comprehensive.
- On pull requests, changed paths determine which expensive jobs execute.

- [ ] **Step 1: Add a lightweight path classification job without third-party path-filter dependencies**

Use `actions/checkout@v7` with `fetch-depth: 0`, then shell/Python against the PR base SHA. Produce `$GITHUB_OUTPUT` booleans. Classification rules:

```text
frontend=true  when frontend/** changes, or CI workflow changes
backend=true   when backend/** changes, or CI workflow changes
docker=true    when backend/**, frontend/Dockerfile, frontend/nginx.conf, backend/Dockerfile,
               docker-compose.yml, deploy.sh, scripts/**, .dockerignore, .env.example,
               or .github/workflows/ci.yml changes
```

For `push`, set all three to true.

- [ ] **Step 2: Add conditions to the existing jobs**

Use:

```yaml
frontend:
  needs: changes
  if: needs.changes.outputs.frontend == 'true'

backend:
  needs: changes
  if: needs.changes.outputs.backend == 'true'

 docker-smoke:
  needs: changes
  if: needs.changes.outputs.docker == 'true'
```

Keep the existing test/build/smoke commands inside each job unchanged.

- [ ] **Step 3: Verify workflow syntax structurally**

Review the complete YAML to ensure `needs`, `if`, and output names match exactly and the workflow-change path forces every job. Because this task edits CI itself, the resulting PR must run all three jobs once.

- [ ] **Step 4: Commit CI gating**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: skip unrelated PR jobs"
```

---

### Task 5: Integrated regression pass, PR, one CI run, and merge

**Files:**
- Review all changed frontend files, `.github/workflows/ci.yml`, spec, and plan.
- No new implementation file is introduced in this task unless a real integration defect is found.

**Interfaces:**
- Final PR must preserve existing manual media start and all approved V2 contracts.

- [ ] **Step 1: Run the full frontend suite once after all tasks are integrated**

```bash
cd frontend
npm test
npm run build
```

Expected: zero Vitest failures and successful `vue-tsc --noEmit && vite build`.

Do not separately run backend tests locally because no backend code changes are planned and this PR's CI workflow edit will conservatively trigger backend + Docker once.

- [ ] **Step 2: Self-review the branch diff against the spec**

Check specifically:

```text
[ ] no native Playback `controls`
[ ] Playback remains staged/manual on page entry
[ ] skip/rate semantics preserved
[ ] event click still uses motionEventSeekTarget
[ ] no Live websocket starts on mount/autofill/assignment
[ ] one tile start opens only one tile connection
[ ] one tile pause closes only that tile connection
[ ] center tile overlay contains only primary action
[ ] hidden tiles stop on layout reduction
[ ] CI workflow change forces this PR to exercise frontend/backend/docker once
[ ] future frontend-only PRs skip backend/docker
```

- [ ] **Step 3: Open one PR**

Title:

```text
feat: unify Protect-style media experience
```

Body should summarize Playback V2, event rail V2, independent Live tile lifecycle, and path-aware CI. Explicitly call out that no backend preview protocol or recording pipeline changed.

- [ ] **Step 4: Run/wait for the single PR CI**

This PR includes `.github/workflows/ci.yml`, so expected jobs are:

```text
changes      success
frontend     success
backend      success
docker-smoke success
```

If a job naturally fails, diagnose and fix the real issue, then rerun as required. Do not create intentional RED CI runs.

- [ ] **Step 5: Final diff review and merge**

If PR CI is green, head SHA is unchanged, and review finds no blocking issue, merge directly. Do not wait for the post-merge `main` CI.

- [ ] **Step 6: Report deployment command**

```bash
git pull && ./deploy.sh
```

Because implementation files are frontend-only plus CI/docs, smart deployment should rebuild/update frontend without restarting backend.
