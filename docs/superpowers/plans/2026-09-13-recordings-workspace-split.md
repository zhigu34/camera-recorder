# Recordings Workspace Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the current hybrid recordings page into a shared “录像” workspace with top tabs for continuous Playback V3 and segment-first Recording Management, while preserving every existing playback/storage/management capability.

**Architecture:** Add a recordings shell that owns the top tabs and route-mode selection. Extract the existing source/fallback video engine into an explicit playback component API, build a native `PlaybackWorkspace.vue` around that API plus `PlaybackTimelineV3` and `PlaybackEventFeed`, and leave `RecordingManagementView.vue` focused on file/segment administration. Remove the current Teleport/MutationObserver bridge only after the native Playback page is verified.

**Tech Stack:** Vue 3.5, TypeScript 5.8, Vue Router 4.5, Pinia 3, Element Plus 2.9, Axios, Vitest 3.2, FastAPI backend unchanged.

**Spec:** `docs/superpowers/specs/2026-09-13-recordings-workspace-split-design.md`

## Global Constraints

- The left sidebar exposes one top-level module named `录像`; Playback and Recording Management are top tabs inside that module.
- `/recordings/playback` is the default continuous playback route.
- `/recordings/manage` is the segment/file administration route.
- `/recordings/browser` redirects to `/recordings/playback` and preserves query/hash.
- Both routes use `navKey: 'recordings'`.
- Tab switches preserve `camera_id`, `date`, and `recording_id`.
- Playback must not render the segment table, batch delete UI, management calendar catalog, storage/health/upload filters, or other segment administration UI.
- Recording Management must preserve camera/date filtering, calendar summaries, segment table, local/cloud state, upload/archive state, health/warnings, batch selection, deletion, compatibility/proxy actions, and diagnostic metadata.
- Playback and Management use one source of truth for direct playback, HEVC handling, H.264 compatibility proxy/live proxy, OpenList/cloud playback, proxy progress, and fallback behavior.
- Timeline seeks use the project wall-clock helpers that intentionally ignore timezone offsets.
- The final Playback implementation must not use document-wide `querySelector`, `MutationObserver`, or Teleport lifecycle tricks for seeking.
- No person/vehicle analytics, storage-format changes, OpenList redesign, auth/permissions, or export-range clipping in this restructuring.
- Do not add new frontend runtime dependencies.

---

### Task 1: Add the recordings route contract and top-tab workspace shell

**Files:**
- Create: `frontend/src/utils/recordingsWorkspace.ts`
- Create: `frontend/src/recordingsWorkspace.test.ts`
- Create: `frontend/src/RecordingsWorkspace.vue`
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/WorkspaceRoute.vue`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Produces: `type RecordingMode = 'playback' | 'manage'`
- Produces: `recordingModeFromMeta(value: unknown): RecordingMode`
- Produces: `recordingTabLocation(mode: RecordingMode, query: LocationQueryRaw, hash?: string): RouteLocationRaw`
- Produces: `RecordingsWorkspace.vue`, which renders the top tabs and switches between Playback and Management using route meta while preserving route query/hash.

- [ ] **Step 1: Write the failing route-helper tests**

Create `frontend/src/recordingsWorkspace.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { recordingModeFromMeta, recordingTabLocation } from './utils/recordingsWorkspace'

describe('recordings workspace navigation', () => {
  it('defaults unknown route meta to playback', () => {
    expect(recordingModeFromMeta(undefined)).toBe('playback')
    expect(recordingModeFromMeta('manage')).toBe('manage')
  })

  it('preserves camera/date/recording context while switching tabs', () => {
    const query = { camera_id: '7', date: '2026-09-13', recording_id: '91', ignored: 'keep' }
    expect(recordingTabLocation('manage', query, '#playback-compatibility')).toEqual({
      path: '/recordings/manage',
      query,
      hash: '#playback-compatibility',
    })
    expect(recordingTabLocation('playback', query, '')).toEqual({
      path: '/recordings/playback',
      query,
      hash: '',
    })
  })
})
```

- [ ] **Step 2: Run the new test and verify RED**

Run from `frontend`:

```bash
npm test -- recordingsWorkspace.test.ts
```

Expected: FAIL because `./utils/recordingsWorkspace` does not exist.

- [ ] **Step 3: Implement the pure route helpers**

Create `frontend/src/utils/recordingsWorkspace.ts`:

```ts
import type { LocationQueryRaw, RouteLocationRaw } from 'vue-router'

export type RecordingMode = 'playback' | 'manage'

export function recordingModeFromMeta(value: unknown): RecordingMode {
  return value === 'manage' ? 'manage' : 'playback'
}

export function recordingTabLocation(
  mode: RecordingMode,
  query: LocationQueryRaw,
  hash = '',
): RouteLocationRaw {
  return {
    path: mode === 'manage' ? '/recordings/manage' : '/recordings/playback',
    query: { ...query },
    hash,
  }
}
```

- [ ] **Step 4: Run the helper test and verify GREEN**

```bash
npm test -- recordingsWorkspace.test.ts
```

Expected: PASS.

- [ ] **Step 5: Add explicit recordings routes**

Change `frontend/src/router.ts` so the recordings records are exactly:

```ts
{
  path: '/recordings/browser',
  redirect: (to) => ({ path: '/recordings/playback', query: to.query, hash: to.hash }),
},
{
  path: '/recordings/playback',
  name: 'recordings-playback',
  component: WorkspaceRoute,
  meta: { navKey: 'recordings', recordingMode: 'playback' },
},
{
  path: '/recordings/manage',
  name: 'recordings-manage',
  component: WorkspaceRoute,
  meta: { navKey: 'recordings', recordingMode: 'manage' },
},
```

Remove the old single `name: 'recordings'` route.

- [ ] **Step 6: Create the shared top-tab shell**

Create `frontend/src/RecordingsWorkspace.vue` with this structure:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PlaybackWorkspace from './PlaybackWorkspace.vue'
import RecordingManagementView from './RecordingManagementView.vue'
import { recordingModeFromMeta, recordingTabLocation } from './utils/recordingsWorkspace'

const route = useRoute()
const router = useRouter()
const mode = computed(() => recordingModeFromMeta(route.meta.recordingMode))

function switchMode(next: 'playback' | 'manage') {
  if (next === mode.value) return
  void router.push(recordingTabLocation(next, route.query, route.hash))
}
</script>

<template>
  <section class="recordings-workspace">
    <nav class="recordings-tabs" aria-label="录像工作区">
      <button :class="{ active: mode === 'playback' }" @click="switchMode('playback')">回放</button>
      <button :class="{ active: mode === 'manage' }" @click="switchMode('manage')">录像管理</button>
    </nav>
    <PlaybackWorkspace v-if="mode === 'playback'" />
    <RecordingManagementView v-else />
  </section>
</template>
```

At this task stage, create a minimal temporary `PlaybackWorkspace.vue` only if the real file does not yet exist, with a single `<div class="playback-workspace-placeholder" />`; Task 4 replaces it before this feature is considered complete. Do not route production users to a blank page before Task 4 is complete on the implementation branch.

- [ ] **Step 7: Wire the shell and sidebar naming**

In `frontend/src/WorkspaceRoute.vue`:

```ts
import RecordingsWorkspace from './RecordingsWorkspace.vue'
```

Replace the recordings branch with:

```vue
<RecordingsWorkspace v-else-if="renderKey === 'recordings'" />
```

In `frontend/src/App.vue`, change the recordings navigation entry to:

```ts
{
  key: 'recordings',
  label: '录像',
  description: '连续回放与录像管理',
  target: '/recordings/playback',
  group: 'core',
  icon: markRaw(Files),
}
```

- [ ] **Step 8: Verify the route shell builds**

```bash
npm test -- recordingsWorkspace.test.ts
npm run build
```

Expected: both commands PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add frontend/src/router.ts frontend/src/WorkspaceRoute.vue frontend/src/App.vue frontend/src/RecordingsWorkspace.vue frontend/src/PlaybackWorkspace.vue frontend/src/utils/recordingsWorkspace.ts frontend/src/recordingsWorkspace.test.ts
git commit -m "feat: split recordings workspace routes"
```

---

### Task 2: Define shared recording/playback types and an explicit player handle

**Files:**
- Create: `frontend/src/types/recordings.ts`
- Create: `frontend/src/utils/playbackOpenRequest.ts`
- Create: `frontend/src/playbackOpenRequest.test.ts`
- Create: `frontend/src/PlaybackPlayer.vue`
- Modify: `frontend/src/RecordingManagementView.vue`

**Interfaces:**
- Produces: shared `RecordingItem`, `PlaybackState`, `ProxyProgress`, and `BrowserResult` types.
- Produces: `PlaybackOpenRequest` and `makePlaybackOpenRequest(recording, seekSeconds, forceCompatibility)`.
- Produces: `PlaybackPlayerHandle`:

```ts
export interface PlaybackPlayerHandle {
  open(recording: RecordingItem, options?: { seekSeconds?: number; forceCompatibility?: boolean }): Promise<void>
  seek(seconds: number): void
  play(): Promise<void>
  pause(): void
}
```

- `PlaybackPlayer.vue` emits `recording-change`, `timeupdate`, `ended`, and `error`.

- [ ] **Step 1: Write RED tests for normalized open requests**

Create `frontend/src/playbackOpenRequest.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { makePlaybackOpenRequest } from './utils/playbackOpenRequest'

const recording = { id: 5, camera_id: 2, status: 'completed', health_status: 'healthy', upload_status: 'success', warning_count: 0, filename: 'a.mp4', playback: { state: 'direct', direct: true } }

describe('playback open request', () => {
  it('clamps a negative seek and preserves compatibility intent', () => {
    expect(makePlaybackOpenRequest(recording, -3, true)).toEqual({
      recording,
      seekSeconds: 0,
      forceCompatibility: true,
    })
  })

  it('normalizes a non-finite seek to zero', () => {
    expect(makePlaybackOpenRequest(recording, Number.NaN, false).seekSeconds).toBe(0)
  })
})
```

- [ ] **Step 2: Run and verify RED**

```bash
npm test -- playbackOpenRequest.test.ts
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Add shared recording types**

Move the existing interfaces from `RecordingManagementView.vue` into `frontend/src/types/recordings.ts` and export them. Preserve field names exactly, including:

```ts
export interface ProxyProgress {
  mode?: 'live' | 'generate' | string
  elapsed_seconds?: number
  duration_seconds?: number
  source_offset_seconds?: number
  percent?: number | null
  running_seconds?: number
  cancellable?: boolean
}

export interface PlaybackState {
  state: 'direct' | 'ready' | 'needed' | 'generating' | 'streaming' | 'error'
  direct: boolean
  error?: string | null
  progress?: ProxyProgress | null
  video_codec?: string | null
  audio_codec?: string | null
  original_available?: boolean
  source_kind?: string
  remote_available?: boolean
  cloud_state?: string
  cloud_error?: string | null
  can_try_original?: boolean
}

export interface RecordingItem {
  id: number
  camera_id: number
  started_at?: string | null
  ended_at?: string | null
  duration?: number | null
  file_size?: number | null
  video_codec?: string | null
  audio_codec?: string | null
  width?: number | null
  height?: number | null
  fps?: number | null
  status: string
  health_status: string
  upload_status: string
  warning_count: number
  timestamp_warning_count?: number
  network_warning_count?: number
  filename: string
  playback: PlaybackState
}

export interface BrowserResult {
  camera_id: number
  date: string
  timezone: string
  count: number
  total_duration: number
  total_size: number
  items: RecordingItem[]
}
```

- [ ] **Step 4: Implement the open-request helper**

Create `frontend/src/utils/playbackOpenRequest.ts`:

```ts
import type { RecordingItem } from '../types/recordings'

export interface PlaybackOpenRequest {
  recording: RecordingItem
  seekSeconds: number
  forceCompatibility: boolean
}

export function makePlaybackOpenRequest(
  recording: RecordingItem,
  seekSeconds = 0,
  forceCompatibility = false,
): PlaybackOpenRequest {
  return {
    recording,
    seekSeconds: Number.isFinite(seekSeconds) ? Math.max(0, seekSeconds) : 0,
    forceCompatibility,
  }
}
```

- [ ] **Step 5: Run and verify GREEN**

```bash
npm test -- playbackOpenRequest.test.ts
```

Expected: PASS.

- [ ] **Step 6: Extract the existing playback engine into `PlaybackPlayer.vue`**

Move, rather than reimplement, the existing direct/original/proxy/proxy-live/cloud playback state and API calls from `RecordingManagementView.vue` into `PlaybackPlayer.vue`. The player component owns:

```ts
const activeRecording = ref<RecordingItem | null>(null)
const videoRef = ref<HTMLVideoElement | null>(null)
const videoSrc = ref('')
const preparing = ref(false)
const playbackMode = ref<'' | 'original' | 'proxy' | 'proxy-live'>('')
const playbackNotice = ref('')
const proxyError = ref('')
const proxyProgress = ref<ProxyProgress | null>(null)
const fallbackInProgress = ref(false)
const cancellingProxy = ref(false)
```

The public methods must use the real video ref, never DOM discovery:

```ts
async function open(recording: RecordingItem, options: { seekSeconds?: number; forceCompatibility?: boolean } = {}) {
  const request = makePlaybackOpenRequest(recording, options.seekSeconds, options.forceCompatibility)
  activeRecording.value = request.recording
  // Continue through the existing direct/proxy/cloud source selection path here.
  // After the chosen source reaches loadedmetadata, call seek(request.seekSeconds).
}

function seek(seconds: number) {
  const video = videoRef.value
  if (!video) return
  const requested = Number.isFinite(seconds) ? Math.max(0, seconds) : 0
  const maximum = Number.isFinite(video.duration) && video.duration > 0
    ? Math.max(0, video.duration - 0.1)
    : requested
  video.currentTime = Math.min(requested, maximum)
}

async function play() {
  await videoRef.value?.play()
}

function pause() {
  videoRef.value?.pause()
}

defineExpose<PlaybackPlayerHandle>({ open, seek, play, pause })
```

Use `<video ref="videoRef">`. Emit `timeupdate` as the numeric segment-relative `currentTime`, and emit `recording-change` whenever `activeRecording` changes.

Do not change endpoint URLs or fallback policy while extracting. Preserve the existing calls and compatibility behavior byte-for-byte where practical.

- [ ] **Step 7: Replace the management page’s inline player with `PlaybackPlayer`**

In `RecordingManagementView.vue`:

- Import the shared types from `./types/recordings`.
- Remove duplicate playback-only refs/functions after they have moved.
- Add `const playerRef = ref<PlaybackPlayerHandle | null>(null)`.
- Change the management `play(item, forceCompatibility)` entry point to:

```ts
async function play(item: RecordingItem, forceCompatibility = false) {
  activeRecording.value = item
  syncRoute(item)
  await nextTick()
  await playerRef.value?.open(item, { forceCompatibility })
}
```

- Render `<PlaybackPlayer ref="playerRef" />` in the existing player panel position.
- Keep management-only adjacent navigation, deletion, filters, calendar, selection, and table behavior in `RecordingManagementView.vue`.

- [ ] **Step 8: Verify extraction compatibility**

```bash
npm test
npm run build
```

Expected: all existing frontend tests PASS and Vue/TypeScript build PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add frontend/src/types/recordings.ts frontend/src/utils/playbackOpenRequest.ts frontend/src/playbackOpenRequest.test.ts frontend/src/PlaybackPlayer.vue frontend/src/RecordingManagementView.vue
git commit -m "refactor: extract recording playback player"
```

---

### Task 3: Define native Playback wall-clock navigation without DOM remounts

**Files:**
- Create: `frontend/src/utils/playbackWorkspaceNavigation.ts`
- Create: `frontend/src/playbackWorkspaceNavigation.test.ts`
- Modify: `frontend/src/utils/playbackSeekStrategy.ts` only if its API becomes redundant after this task.

**Interfaces:**
- Consumes: `TimelineRecording`, `findRecordingAtWallTime`, `recordingSeekOffset`.
- Produces:

```ts
export type PlaybackWallClockAction =
  | { kind: 'gap'; wallSeconds: number }
  | { kind: 'seek'; wallSeconds: number; recordingId: number; seekSeconds: number; switchRecording: boolean }

export function playbackWallClockAction(
  currentRecordingId: number | null,
  recordings: TimelineRecording[],
  wallSeconds: number,
): PlaybackWallClockAction
```

- [ ] **Step 1: Write RED tests for gap, same-recording, and cross-recording behavior**

Create `frontend/src/playbackWorkspaceNavigation.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { playbackWallClockAction } from './utils/playbackWorkspaceNavigation'

const recordings = [
  { id: 10, started_at: '2026-09-13T10:00:00+08:00', ended_at: '2026-09-13T10:10:00+08:00', duration: 600 },
  { id: 11, started_at: '2026-09-13T10:20:00+08:00', ended_at: '2026-09-13T10:30:00+08:00', duration: 600 },
]

describe('playback wall-clock navigation', () => {
  it('keeps same-recording seeks in place', () => {
    expect(playbackWallClockAction(10, recordings, 10 * 3600 + 30)).toEqual({
      kind: 'seek', wallSeconds: 36030, recordingId: 10, seekSeconds: 30, switchRecording: false,
    })
  })

  it('requests a source switch for another recording', () => {
    expect(playbackWallClockAction(10, recordings, 10 * 3600 + 20 * 60 + 15)).toEqual({
      kind: 'seek', wallSeconds: 37215, recordingId: 11, seekSeconds: 15, switchRecording: true,
    })
  })

  it('does not invent a recording in a gap', () => {
    expect(playbackWallClockAction(10, recordings, 10 * 3600 + 15 * 60)).toEqual({
      kind: 'gap', wallSeconds: 36900,
    })
  })
})
```

- [ ] **Step 2: Run and verify RED**

```bash
npm test -- playbackWorkspaceNavigation.test.ts
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement the pure navigation action**

Create `frontend/src/utils/playbackWorkspaceNavigation.ts`:

```ts
import {
  findRecordingAtWallTime,
  recordingSeekOffset,
  type TimelineRecording,
} from './playbackTimelineV3'

export type PlaybackWallClockAction =
  | { kind: 'gap'; wallSeconds: number }
  | { kind: 'seek'; wallSeconds: number; recordingId: number; seekSeconds: number; switchRecording: boolean }

export function playbackWallClockAction(
  currentRecordingId: number | null,
  recordings: TimelineRecording[],
  wallSeconds: number,
): PlaybackWallClockAction {
  const recording = findRecordingAtWallTime(recordings, wallSeconds)
  if (!recording) return { kind: 'gap', wallSeconds }
  return {
    kind: 'seek',
    wallSeconds,
    recordingId: recording.id,
    seekSeconds: recordingSeekOffset(recording, wallSeconds),
    switchRecording: recording.id !== currentRecordingId,
  }
}
```

- [ ] **Step 4: Run and verify GREEN**

```bash
npm test -- playbackWorkspaceNavigation.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run all Playback V3 behavior tests**

```bash
npm test -- playbackTimelineV3.test.ts playbackTimelineV3.interaction.test.ts playbackWorkspaceNavigation.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add frontend/src/utils/playbackWorkspaceNavigation.ts frontend/src/playbackWorkspaceNavigation.test.ts frontend/src/utils/playbackSeekStrategy.ts
git commit -m "test: define native playback navigation"
```

---

### Task 4: Build the native Playback V3 workspace and remove Teleport/MutationObserver seeking

**Files:**
- Replace: `frontend/src/PlaybackWorkspace.vue`
- Modify: `frontend/src/PlaybackEventFeed.vue`
- Modify: `frontend/src/PlaybackTimelineV3.vue` only if prop types must use shared types.
- Modify: `frontend/src/utils/playbackTimelineV3.ts` only for shared type compatibility.
- Delete after migration: `frontend/src/RecordingManagementWorkspace.vue`

**Interfaces:**
- Consumes: `PlaybackPlayerHandle`, `PlaybackTimelineV3`, `PlaybackEventFeed`, `playbackWallClockAction`.
- Playback owns selected camera/date, day recordings, active recording ID, and active wall-clock seconds.
- `PlaybackPlayer` is controlled only through its Vue ref handle.

- [ ] **Step 1: Add a pure initial-selection test**

Extend `frontend/src/playbackWorkspaceNavigation.test.ts` with:

```ts
import { resolvePlaybackSelection } from './utils/playbackWorkspaceNavigation'

it('prefers a valid deep-linked recording and falls back to the first day recording', () => {
  expect(resolvePlaybackSelection(recordings, 11)?.id).toBe(11)
  expect(resolvePlaybackSelection(recordings, 999)?.id).toBe(10)
  expect(resolvePlaybackSelection([], 11)).toBeNull()
})
```

- [ ] **Step 2: Verify RED**

```bash
npm test -- playbackWorkspaceNavigation.test.ts
```

Expected: FAIL because `resolvePlaybackSelection` is not exported.

- [ ] **Step 3: Implement deterministic deep-link selection**

Add to `frontend/src/utils/playbackWorkspaceNavigation.ts`:

```ts
export function resolvePlaybackSelection(
  recordings: TimelineRecording[],
  recordingId: number | null,
): TimelineRecording | null {
  if (recordingId) {
    const exact = recordings.find((item) => item.id === recordingId)
    if (exact) return exact
  }
  return recordings[0] || null
}
```

- [ ] **Step 4: Verify GREEN**

```bash
npm test -- playbackWorkspaceNavigation.test.ts
```

Expected: PASS.

- [ ] **Step 5: Implement `PlaybackWorkspace.vue` state and loading**

The component must:

```ts
const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const playerRef = ref<PlaybackPlayerHandle | null>(null)
const recordings = ref<RecordingItem[]>([])
const activeRecordingId = ref<number | null>(null)
const activeWallSeconds = ref<number | null>(null)
const selectedCamera = ref<number | null>(null)
const selectedDate = ref(todayString())
```

Load cameras and `/api/recordings/browser?camera_id=...&date=...`. If route context is incomplete, reuse the existing recent-recording endpoint/selection behavior from `RecordingManagementView.vue` so the route resolves a useful camera/date instead of showing a blank page.

Normalize the route after selection:

```ts
function syncPlaybackRoute(recordingId: number | null = activeRecordingId.value) {
  const query: Record<string, string> = {}
  if (selectedCamera.value) query.camera_id = String(selectedCamera.value)
  if (selectedDate.value) query.date = selectedDate.value
  if (recordingId) query.recording_id = String(recordingId)
  void router.replace({ path: '/recordings/playback', query })
}
```

- [ ] **Step 6: Implement explicit timeline/event seeking**

Use the pure action and player handle:

```ts
async function seekWallClock(wallSeconds: number) {
  const action = playbackWallClockAction(activeRecordingId.value, recordings.value, wallSeconds)
  if (action.kind === 'gap') {
    ElMessage.info('该时间没有可播放录像')
    return
  }

  const recording = recordings.value.find((item) => item.id === action.recordingId)
  if (!recording) return

  if (action.switchRecording) {
    activeRecordingId.value = recording.id
    syncPlaybackRoute(recording.id)
    await playerRef.value?.open(recording, { seekSeconds: action.seekSeconds })
  } else {
    playerRef.value?.seek(action.seekSeconds)
    await playerRef.value?.play().catch(() => undefined)
  }
  activeWallSeconds.value = action.wallSeconds
}
```

No `document.querySelector`, `MutationObserver`, `viewKey`, or Teleport is permitted in this component.

- [ ] **Step 7: Wire video time back to wall-clock time**

When `PlaybackPlayer` emits segment-relative `timeupdate`, map it through the active recording start using `wallClockSeconds`:

```ts
function handlePlayerTime(seconds: number) {
  const recording = recordings.value.find((item) => item.id === activeRecordingId.value)
  const start = recording ? wallClockSeconds(recording.started_at) : null
  if (start === null) return
  activeWallSeconds.value = Math.max(0, Math.min(86400, start + Math.max(0, seconds)))
}
```

- [ ] **Step 8: Render the Playback-only hierarchy**

The template order must be:

```vue
<section class="playback-workspace">
  <header class="playback-context-bar">
    <!-- compact camera selector, date picker, 管理当前录像 action -->
  </header>

  <div class="playback-main-grid">
    <PlaybackPlayer ref="playerRef" @timeupdate="handlePlayerTime" />
    <PlaybackEventFeed
      v-if="selectedCamera"
      :camera-id="selectedCamera"
      :date="selectedDate"
      :recordings="recordings"
      :active-wall-seconds="activeWallSeconds"
      @seek="seekWallClock"
    />
  </div>

  <PlaybackTimelineV3
    v-if="selectedCamera"
    :camera-id="selectedCamera"
    :date="selectedDate"
    :recordings="recordings"
    :active-wall-seconds="activeWallSeconds"
    @seek="seekWallClock"
  />
</section>
```

Do not include `el-table`, batch selection, delete buttons, storage/health/upload filters, or the management calendar.

- [ ] **Step 9: Add “管理当前录像” deep link**

```ts
function openManagement() {
  void router.push(recordingTabLocation('manage', route.query, ''))
}
```

If there is no active recording, retain camera/date and omit/ignore stale `recording_id` when normalizing the Playback route.

- [ ] **Step 10: Remove the legacy bridge**

Delete `frontend/src/RecordingManagementWorkspace.vue` after `WorkspaceRoute.vue` no longer imports it. This deletion removes the old `MutationObserver`, document-level video lookup, Teleports, and `viewKey` remount path.

- [ ] **Step 11: Verify native Playback**

```bash
npm test
npm run build
```

Expected: all tests PASS; production build PASS.

Manually inspect the generated source or repository search and confirm these strings no longer exist in the recordings Playback integration path:

```text
MutationObserver
.recording-center .player-box video
<Teleport
viewKey
```

`Teleport` may still exist elsewhere in the product for unrelated UI; the requirement is that Playback V3 no longer depends on it.

- [ ] **Step 12: Commit Task 4**

```bash
git add frontend/src/PlaybackWorkspace.vue frontend/src/PlaybackEventFeed.vue frontend/src/PlaybackTimelineV3.vue frontend/src/utils/playbackTimelineV3.ts frontend/src/utils/playbackWorkspaceNavigation.ts frontend/src/playbackWorkspaceNavigation.test.ts frontend/src/WorkspaceRoute.vue
git rm frontend/src/RecordingManagementWorkspace.vue
git commit -m "feat: make playback v3 a native workspace"
```

---

### Task 5: Preserve Recording Management and add bidirectional deep links

**Files:**
- Modify: `frontend/src/RecordingManagementView.vue`
- Create: `frontend/src/utils/recordingDeepLinks.ts`
- Create: `frontend/src/recordingDeepLinks.test.ts`

**Interfaces:**
- Produces: `playbackLocationForRecording(recording: RecordingItem): RouteLocationRaw`
- Produces: `managementLocationForContext(cameraId, date, recordingId): RouteLocationRaw`

- [ ] **Step 1: Write RED deep-link tests**

Create `frontend/src/recordingDeepLinks.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { playbackLocationForRecording, managementLocationForContext } from './utils/recordingDeepLinks'

const recording = {
  id: 91,
  camera_id: 7,
  started_at: '2026-09-13T16:20:00+08:00',
  status: 'completed', health_status: 'healthy', upload_status: 'success', warning_count: 0,
  filename: '91.mp4', playback: { state: 'direct', direct: true },
}

describe('recording deep links', () => {
  it('opens a managed segment in playback with camera/date/id context', () => {
    expect(playbackLocationForRecording(recording)).toEqual({
      path: '/recordings/playback',
      query: { camera_id: '7', date: '2026-09-13', recording_id: '91' },
    })
  })

  it('opens management with camera/date even when no recording is active', () => {
    expect(managementLocationForContext(7, '2026-09-13', null)).toEqual({
      path: '/recordings/manage',
      query: { camera_id: '7', date: '2026-09-13' },
    })
  })
})
```

- [ ] **Step 2: Run and verify RED**

```bash
npm test -- recordingDeepLinks.test.ts
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement exact deep-link helpers**

Create `frontend/src/utils/recordingDeepLinks.ts`:

```ts
import type { RouteLocationRaw } from 'vue-router'
import type { RecordingItem } from '../types/recordings'

function recordingDate(value?: string | null) {
  return value && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null
}

export function playbackLocationForRecording(recording: RecordingItem): RouteLocationRaw {
  const query: Record<string, string> = {
    camera_id: String(recording.camera_id),
    recording_id: String(recording.id),
  }
  const date = recordingDate(recording.started_at)
  if (date) query.date = date
  return { path: '/recordings/playback', query }
}

export function managementLocationForContext(
  cameraId: number | null,
  date: string | null,
  recordingId: number | null,
): RouteLocationRaw {
  const query: Record<string, string> = {}
  if (cameraId) query.camera_id = String(cameraId)
  if (date) query.date = date
  if (recordingId) query.recording_id = String(recordingId)
  return { path: '/recordings/manage', query }
}
```

- [ ] **Step 4: Run and verify GREEN**

```bash
npm test -- recordingDeepLinks.test.ts
```

Expected: PASS.

- [ ] **Step 5: Change management row playback behavior**

Keep single-click row selection for administration. Change double-click and the explicit playback action to:

```ts
function openInPlayback(item: RecordingItem) {
  void router.push(playbackLocationForRecording(item))
}
```

The row/table remains present in Management. Do not remove selection, batch delete, compatibility, cloud/local columns, health/upload filters, or calendar controls.

- [ ] **Step 6: Keep compatibility actions inside Management**

The compatibility menu still calls the extracted `PlaybackPlayer` with:

```ts
await playerRef.value?.open(item, { forceCompatibility: true })
```

This is an operational management action and must not be converted to a Playback route redirect.

- [ ] **Step 7: Verify management build and behavior tests**

```bash
npm test -- recordingDeepLinks.test.ts playbackOpenRequest.test.ts
npm run build
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```bash
git add frontend/src/RecordingManagementView.vue frontend/src/utils/recordingDeepLinks.ts frontend/src/recordingDeepLinks.test.ts
git commit -m "feat: link recording management and playback"
```

---

### Task 6: Route every product entry point to the correct recordings tab

**Files:**
- Modify: `frontend/src/PreviewView.vue`
- Modify: `frontend/src/EventCenterView.vue`
- Modify: `frontend/src/UploadManagementView.vue`
- Modify: `frontend/src/WorkspaceRoute.vue`
- Modify: `frontend/src/App.vue`
- Modify other files only when repository search finds a hard-coded `/recordings/manage` or `/recordings/browser` whose intent is clearly playback.

**Interfaces:**
- Viewing intent -> `/recordings/playback`.
- File/archive/compatibility administration intent -> `/recordings/manage`.

- [ ] **Step 1: Add a static route-intent regression test**

Create `frontend/src/recordingRouteIntent.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { recordingIntentPath } from './utils/recordingsWorkspace'

describe('recordings route intent', () => {
  it('separates viewing from administration', () => {
    expect(recordingIntentPath('view')).toBe('/recordings/playback')
    expect(recordingIntentPath('manage')).toBe('/recordings/manage')
  })
})
```

- [ ] **Step 2: Verify RED**

```bash
npm test -- recordingRouteIntent.test.ts
```

Expected: FAIL because `recordingIntentPath` does not exist.

- [ ] **Step 3: Implement the intent helper**

Add to `frontend/src/utils/recordingsWorkspace.ts`:

```ts
export function recordingIntentPath(intent: 'view' | 'manage') {
  return intent === 'manage' ? '/recordings/manage' : '/recordings/playback'
}
```

- [ ] **Step 4: Verify GREEN**

```bash
npm test -- recordingRouteIntent.test.ts
```

Expected: PASS.

- [ ] **Step 5: Update Live Monitoring playback actions**

In `PreviewView.vue`, replace the generic `openPlayback()` with camera-aware routing:

```ts
function openPlayback(cameraId: number | null) {
  const query = cameraId ? { camera_id: String(cameraId) } : undefined
  void router.push({ path: '/recordings/playback', query })
}
```

Change the slot action to `@click="openPlayback(slot.cameraId)"`.

- [ ] **Step 6: Update Event Center viewing actions**

Any action whose copy means “查看录像/回放/查看事件录像” must emit or route to `/recordings/playback`, preserving known camera/date/recording context. Keep administration links to `/recordings/manage` only when the action is explicitly about file/segment administration.

- [ ] **Step 7: Keep Upload and compatibility operational links on Management**

`UploadManagementView`’s “open recordings” administration action remains `/recordings/manage`.

In `WorkspaceRoute.vue`, keep `openPlaybackCompatibility()` on `/recordings/manage#playback-compatibility` because it is an operational compatibility tool, not a viewing action.

- [ ] **Step 8: Search for stale route consumers**

Run:

```bash
grep -R "'/recordings/manage\|\"/recordings/manage\|'/recordings/browser\|\"/recordings/browser" frontend/src
```

Classify every result by intent. Viewing links must point to Playback; administration/compatibility links remain Management. There must be no remaining `/recordings/browser` consumer except the router compatibility redirect.

- [ ] **Step 9: Verify frontend**

```bash
npm test
npm run build
```

Expected: PASS.

- [ ] **Step 10: Commit Task 6**

```bash
git add frontend/src/PreviewView.vue frontend/src/EventCenterView.vue frontend/src/UploadManagementView.vue frontend/src/WorkspaceRoute.vue frontend/src/App.vue frontend/src/utils/recordingsWorkspace.ts frontend/src/recordingRouteIntent.test.ts
git commit -m "refactor: route recording intents to playback or management"
```

---

### Task 7: Remove legacy Playback V3 hybrid CSS/state and document the supersession

**Files:**
- Modify: `frontend/src/styles/recording-management.css` only if it contains workspace-level assumptions that no longer apply.
- Modify: `frontend/src/RecordingManagementView.vue`
- Modify: `docs/superpowers/specs/2026-09-13-playback-v3-design.md`
- Modify: `docs/superpowers/specs/2026-09-13-recordings-workspace-split-design.md` only to record final implemented component names if they differ from the design.

**Interfaces:**
- No new runtime interface.
- Final source architecture has `RecordingsWorkspace` -> `PlaybackWorkspace` or `RecordingManagementView`.

- [ ] **Step 1: Remove obsolete hidden-heat-map and Teleport-target assumptions**

Delete CSS and state that existed only to let `RecordingManagementWorkspace.vue` inject V3 UI into `.recording-center .recording-layout`, including rules equivalent to:

```css
.recording-center .heat-section { display: none !important; }
.recording-center .recording-layout > .playback-v3 { grid-column: 1 / -1; }
.recording-center .catalog-column > .playback-event-feed { order: -1; }
```

Management may keep its own heat map if it still serves administration/diagnostics; Playback must not rely on hiding it with cross-component CSS.

- [ ] **Step 2: Mark the original Playback V3 design as superseded where necessary**

Add this note near the top of `docs/superpowers/specs/2026-09-13-playback-v3-design.md`:

```md
> Architecture update: the “right-side catalog remains secondary” layout and the `RecordingManagementWorkspace` compatibility bridge are superseded by `2026-09-13-recordings-workspace-split-design.md`. Timeline math, wall-clock semantics, Motion behavior, and playback fallback requirements remain in force.
```

- [ ] **Step 3: Run source-structure checks**

```bash
! test -f frontend/src/RecordingManagementWorkspace.vue
grep -R "MutationObserver" frontend/src | grep -v PreviewView || true
grep -R "recording-center .player-box video" frontend/src && exit 1 || true
grep -R "to=\".recording-center" frontend/src && exit 1 || true
```

Expected: legacy workspace file absent; no Playback-specific global DOM bridge remains.

- [ ] **Step 4: Run complete frontend verification**

```bash
cd frontend
npm test
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```bash
git add frontend/src frontend/src/styles/recording-management.css docs/superpowers/specs/2026-09-13-playback-v3-design.md docs/superpowers/specs/2026-09-13-recordings-workspace-split-design.md
git commit -m "cleanup: retire hybrid playback workspace"
```

---

### Task 8: Full regression verification and deployment readiness

**Files:**
- No code changes unless verification exposes a real regression.
- Verify: `.github/workflows/ci.yml`

**Interfaces:**
- Final acceptance gate only.

- [ ] **Step 1: Run the complete frontend suite locally/CI-equivalent**

```bash
cd frontend
npm test
npm run build
```

Expected: all Vitest tests PASS; `vue-tsc --noEmit` and Vite production build PASS.

- [ ] **Step 2: Run backend regression suite**

From repository root:

```bash
uv run python -m compileall app
uv run python -m pytest
```

Expected: PASS; no backend behavior was intentionally changed.

- [ ] **Step 3: Run/observe docker-smoke**

Use the repository CI workflow and require the `docker-smoke` job to complete these existing checks successfully: deployment script validation, compose config, backend/frontend image build, compose up, backend health, backend internal-only exposure check, frontend availability, backend-health proxy, upload WebSocket proxy, cleanup.

- [ ] **Step 4: Acceptance-check the recordings UX**

Verify all of the following in the built app:

```text
/recordings/playback -> 回放 tab active, no segment table
/recordings/manage   -> 录像管理 tab active, full segment administration present
/recordings/browser?camera_id=...&date=... -> redirects to playback with query preserved
Playback -> 录像管理 tab -> camera/date/recording context preserved
Management row -> 在回放中打开 -> playback opens matching camera/date/recording
Timeline click in same recording -> in-place seek, workspace stays mounted
Timeline click in another recording -> source switch + correct seek offset
Timeline click in gap -> current source unchanged + “该时间没有可播放录像”
Repeated Motion event click -> timeline remains mounted
Direct HEVC/H.264, compatibility proxy/live proxy, cloud/OpenList fallback behavior still works
```

- [ ] **Step 5: Confirm final `main` HEAD and CI status before declaring complete**

Do not claim completion until frontend, backend, and docker-smoke are all green for the same final commit SHA.

- [ ] **Step 6: Deployment handoff**

After the final SHA is green, the user deployment command is exactly:

```bash
git pull && ./deploy.sh
```

Do not require `docker image prune -f`.
