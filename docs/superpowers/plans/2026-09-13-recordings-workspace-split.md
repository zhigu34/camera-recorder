# Recordings Workspace Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the hybrid recordings page into one “录像” module with top tabs for continuous Playback V3 and segment-first Recording Management, without losing playback, cloud, compatibility, deletion, or diagnostic capabilities.

**Architecture:** `RecordingsWorkspace.vue` owns the top tabs and route mode. `PlaybackPlayer.vue` becomes the single explicit video/source/fallback engine used by both surfaces. `PlaybackWorkspace.vue` owns camera/date selection, day recordings, event feed and continuous timeline; `RecordingManagementView.vue` keeps segment administration. The current `RecordingManagementWorkspace.vue` Teleport/MutationObserver bridge is removed after the native Playback page is wired.

**Tech Stack:** Vue 3.5, TypeScript 5.8, Vue Router 4.5, Pinia 3, Element Plus 2.9, Axios, Vitest 3.2. Backend APIs and storage remain unchanged.

**Spec:** `docs/superpowers/specs/2026-09-13-recordings-workspace-split-design.md`

## Global Constraints

- Sidebar has one `录像` entry targeting `/recordings/playback`.
- `/recordings/playback` = Playback V3; `/recordings/manage` = segment/file administration.
- `/recordings/browser` redirects to Playback and preserves query/hash.
- Both routes use `navKey: 'recordings'`.
- Top-tab switches preserve `camera_id`, `date`, and `recording_id`.
- Playback must not render the segment table, batch delete controls, management calendar catalog, or storage/health/upload filters.
- Management must preserve current segment filtering, calendar, local/cloud state, upload state, health/warnings, batch selection, deletion, compatibility actions and metadata.
- Direct/original playback, HEVC handling, H.264 compatibility proxy/live proxy, OpenList/cloud playback, progress and fallback behavior have one implementation.
- Timeline wall-clock math continues to ignore timestamp offsets exactly as current `wallClockSeconds()` does.
- Final Playback seeking must not depend on document-wide `querySelector`, `MutationObserver`, Teleport target discovery, or `viewKey` remounts.
- No new frontend runtime dependency.
- No person/vehicle analytics, export clipping, auth, storage-format change, or OpenList redesign in this work.

---

### Task 1: Add explicit recordings routes and the top-tab shell

**Files:**
- Create: `frontend/src/utils/recordingsWorkspace.ts`
- Create: `frontend/src/recordingsWorkspace.test.ts`
- Create: `frontend/src/RecordingsWorkspace.vue`
- Create: `frontend/src/PlaybackWorkspace.vue` as a working compatibility wrapper for this task only
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/WorkspaceRoute.vue`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Produces `RecordingMode = 'playback' | 'manage'`.
- Produces `recordingModeFromMeta()` and `recordingTabLocation()`.
- `RecordingsWorkspace.vue` renders the top tabs and chooses Playback or Management from route meta.

- [ ] **Step 1: Write the failing helper test**

Create `frontend/src/recordingsWorkspace.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { recordingModeFromMeta, recordingTabLocation } from './utils/recordingsWorkspace'

describe('recordings workspace', () => {
  it('defaults unknown mode to playback', () => {
    expect(recordingModeFromMeta(undefined)).toBe('playback')
    expect(recordingModeFromMeta('manage')).toBe('manage')
  })

  it('preserves query and hash across tabs', () => {
    const query = { camera_id: '7', date: '2026-09-13', recording_id: '91' }
    expect(recordingTabLocation('manage', query, '#playback-compatibility')).toEqual({
      path: '/recordings/manage', query, hash: '#playback-compatibility',
    })
    expect(recordingTabLocation('playback', query, '')).toEqual({
      path: '/recordings/playback', query, hash: '',
    })
  })
})
```

- [ ] **Step 2: Run RED**

```bash
cd frontend
npm test -- recordingsWorkspace.test.ts
```

Expected: FAIL because `utils/recordingsWorkspace.ts` does not exist.

- [ ] **Step 3: Implement the helper**

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

export function recordingIntentPath(intent: 'view' | 'manage') {
  return intent === 'manage' ? '/recordings/manage' : '/recordings/playback'
}
```

- [ ] **Step 4: Run GREEN**

```bash
npm test -- recordingsWorkspace.test.ts
```

Expected: PASS.

- [ ] **Step 5: Replace the router records**

In `frontend/src/router.ts`, recordings routes become:

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

- [ ] **Step 6: Create a working compatibility Playback wrapper**

Create `frontend/src/PlaybackWorkspace.vue`:

```vue
<script setup lang="ts">
import RecordingManagementWorkspace from './RecordingManagementWorkspace.vue'
</script>

<template>
  <RecordingManagementWorkspace />
</template>
```

This keeps the branch functional until Task 3 replaces this file with the native Playback implementation.

- [ ] **Step 7: Create the top-tab shell**

Create `frontend/src/RecordingsWorkspace.vue`:

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
      <button type="button" :class="{ active: mode === 'playback' }" @click="switchMode('playback')">回放</button>
      <button type="button" :class="{ active: mode === 'manage' }" @click="switchMode('manage')">录像管理</button>
    </nav>
    <PlaybackWorkspace v-if="mode === 'playback'" />
    <RecordingManagementView v-else />
  </section>
</template>
```

Add scoped styles so the tabs sit directly below the global top bar, use the existing NVR surface/border/text tokens, and do not create dashboard cards around the content.

- [ ] **Step 8: Wire shell and sidebar**

`WorkspaceRoute.vue` imports `RecordingsWorkspace` and uses:

```vue
<RecordingsWorkspace v-else-if="renderKey === 'recordings'" />
```

`App.vue` recordings entry becomes:

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

- [ ] **Step 9: Verify and commit**

```bash
npm test -- recordingsWorkspace.test.ts
npm run build
git add src/router.ts src/WorkspaceRoute.vue src/App.vue src/RecordingsWorkspace.vue src/PlaybackWorkspace.vue src/utils/recordingsWorkspace.ts src/recordingsWorkspace.test.ts
git commit -m "feat: split recordings workspace routes"
```

---

### Task 2: Extract the current playback engine behind an explicit Vue ref API

**Files:**
- Create: `frontend/src/types/recordings.ts`
- Create: `frontend/src/utils/playbackOpenRequest.ts`
- Create: `frontend/src/playbackOpenRequest.test.ts`
- Create: `frontend/src/PlaybackPlayer.vue`
- Modify: `frontend/src/RecordingManagementView.vue`

**Interfaces:**

```ts
export interface PlaybackPlayerHandle {
  open(recording: RecordingItem, options?: { seekSeconds?: number; forceCompatibility?: boolean }): Promise<void>
  seek(seconds: number): void
  play(): Promise<void>
  pause(): void
}
```

`PlaybackPlayer.vue` emits `timeupdate: [seconds: number]`, `recording-change: [recording: RecordingItem | null]`, `ended: []`, and `error: [message: string]`.

- [ ] **Step 1: Write RED normalization tests**

Create `frontend/src/playbackOpenRequest.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { makePlaybackOpenRequest } from './utils/playbackOpenRequest'

const recording = {
  id: 5,
  camera_id: 2,
  status: 'completed',
  health_status: 'healthy',
  upload_status: 'success',
  warning_count: 0,
  filename: 'a.mp4',
  playback: { state: 'direct' as const, direct: true },
}

describe('playback open request', () => {
  it('clamps negative seek and preserves compatibility intent', () => {
    expect(makePlaybackOpenRequest(recording, -3, true)).toEqual({
      recording, seekSeconds: 0, forceCompatibility: true,
    })
  })

  it('normalizes non-finite seek to zero', () => {
    expect(makePlaybackOpenRequest(recording, Number.NaN, false).seekSeconds).toBe(0)
  })
})
```

- [ ] **Step 2: Run RED**

```bash
npm test -- playbackOpenRequest.test.ts
```

Expected: FAIL because the helper is missing.

- [ ] **Step 3: Move shared types out of the management view**

Create `frontend/src/types/recordings.ts` with the existing `ProxyProgress`, `PlaybackState`, `RecordingItem`, and `BrowserResult` interfaces, preserving every current field name and optionality. Replace the inline copies in `RecordingManagementView.vue` with imports from this file.

- [ ] **Step 4: Implement request normalization**

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

- [ ] **Step 5: Run GREEN**

```bash
npm test -- playbackOpenRequest.test.ts
```

Expected: PASS.

- [ ] **Step 6: Move the playback-only state and functions unchanged into `PlaybackPlayer.vue`**

Move these existing functions from `RecordingManagementView.vue` into `PlaybackPlayer.vue` without changing endpoint URLs or fallback ordering:

```text
codecName
isH264
isHevc
streamUrl
liveProxyUrl
metricSourceKind
beginPlaybackSource
stopProgressPolling
refreshProxyProgress
startProgressPolling
prepareProxy
cancelProxy
currentVideo
handleLoadedMetadata
handleLoadedData
handleVideoCanPlay
handleVideoPlaying
handleVideoError
```

Also move the current direct/original/proxy/proxy-live/cloud branch from `play(item, forceCompatibility)` into the new public `open()` method. Keep the existing calls to `/api/recordings/{id}/playback`, `/api/recordings/{id}/stream`, `/api/recordings/{id}/proxy-live.mp4`, and `/api/recordings/{id}/playback/cancel` exactly as they are now.

The new component owns these refs:

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

The explicit player control code is:

```ts
function seek(seconds: number) {
  const video = videoRef.value
  if (!video) return
  const requested = Number.isFinite(seconds) ? Math.max(0, seconds) : 0
  const maximum = Number.isFinite(video.duration) && video.duration > 0
    ? Math.max(0, video.duration - 0.1)
    : requested
  video.currentTime = Math.min(requested, maximum)
}

async function playVideo() {
  if (videoRef.value) await videoRef.value.play()
}

function pause() {
  videoRef.value?.pause()
}

function handleTimeUpdate() {
  emit('timeupdate', Math.max(0, Number(videoRef.value?.currentTime || 0)))
}

defineExpose<PlaybackPlayerHandle>({
  open,
  seek,
  play: playVideo,
  pause,
})
```

Use `<video ref="videoRef" @timeupdate="handleTimeUpdate">` and keep all existing metadata/canplay/playing/error handlers attached.

- [ ] **Step 7: Make `open()` apply a requested offset after metadata**

Store the normalized request seek in a component ref:

```ts
const pendingSeekSeconds = ref<number | null>(null)

async function open(recording: RecordingItem, options: { seekSeconds?: number; forceCompatibility?: boolean } = {}) {
  const request = makePlaybackOpenRequest(recording, options.seekSeconds, options.forceCompatibility)
  pendingSeekSeconds.value = request.seekSeconds
  activeRecording.value = request.recording
  emit('recording-change', request.recording)
  await openRecordingSource(request.recording, request.forceCompatibility)
}

function applyPendingSeek() {
  if (pendingSeekSeconds.value === null) return
  seek(pendingSeekSeconds.value)
  pendingSeekSeconds.value = null
}
```

Rename the moved body of the old `play()` to:

```ts
async function openRecordingSource(item: RecordingItem, forceCompatibility = false): Promise<void>
```

Call `applyPendingSeek()` from `handleLoadedMetadata()` after `playbackTracker.markLoadedMetadata()`.

- [ ] **Step 8: Replace the management page inline player with the extracted component**

In `RecordingManagementView.vue`:

```ts
const playerRef = ref<PlaybackPlayerHandle | null>(null)

async function play(item: RecordingItem, forceCompatibility = false) {
  activeRecording.value = item
  syncRoute(item)
  await nextTick()
  await playerRef.value?.open(item, { forceCompatibility })
}
```

Render `PlaybackPlayer` in the current player panel. Keep management-only adjacent navigation, table selection, calendar, filters and deletion in `RecordingManagementView.vue`.

- [ ] **Step 9: Verify and commit**

```bash
npm test
npm run build
git add src/types/recordings.ts src/utils/playbackOpenRequest.ts src/playbackOpenRequest.test.ts src/PlaybackPlayer.vue src/RecordingManagementView.vue
git commit -m "refactor: extract recording playback player"
```

---

### Task 3: Replace the compatibility wrapper with a native Playback V3 workspace

**Files:**
- Create: `frontend/src/utils/playbackWorkspaceNavigation.ts`
- Create: `frontend/src/playbackWorkspaceNavigation.test.ts`
- Replace: `frontend/src/PlaybackWorkspace.vue`
- Modify: `frontend/src/PlaybackEventFeed.vue`
- Modify: `frontend/src/PlaybackTimelineV3.vue` only for shared type imports
- Delete: `frontend/src/RecordingManagementWorkspace.vue`

**Interfaces:**

```ts
export type PlaybackWallClockAction =
  | { kind: 'gap'; wallSeconds: number }
  | { kind: 'seek'; wallSeconds: number; recordingId: number; seekSeconds: number; switchRecording: boolean }
```

- [ ] **Step 1: Write RED navigation tests**

Create `frontend/src/playbackWorkspaceNavigation.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { playbackWallClockAction, resolvePlaybackSelection } from './utils/playbackWorkspaceNavigation'

const recordings = [
  { id: 10, started_at: '2026-09-13T10:00:00+08:00', ended_at: '2026-09-13T10:10:00+08:00', duration: 600 },
  { id: 11, started_at: '2026-09-13T10:20:00+08:00', ended_at: '2026-09-13T10:30:00+08:00', duration: 600 },
]

describe('playback workspace navigation', () => {
  it('seeks in place inside the current recording', () => {
    expect(playbackWallClockAction(10, recordings, 36030)).toEqual({
      kind: 'seek', wallSeconds: 36030, recordingId: 10, seekSeconds: 30, switchRecording: false,
    })
  })

  it('switches source for another recording', () => {
    expect(playbackWallClockAction(10, recordings, 37215)).toEqual({
      kind: 'seek', wallSeconds: 37215, recordingId: 11, seekSeconds: 15, switchRecording: true,
    })
  })

  it('keeps gaps as gaps', () => {
    expect(playbackWallClockAction(10, recordings, 36900)).toEqual({ kind: 'gap', wallSeconds: 36900 })
  })

  it('prefers a valid deep link and otherwise selects the first day recording', () => {
    expect(resolvePlaybackSelection(recordings, 11)?.id).toBe(11)
    expect(resolvePlaybackSelection(recordings, 999)?.id).toBe(10)
    expect(resolvePlaybackSelection([], 11)).toBeNull()
  })
})
```

- [ ] **Step 2: Run RED**

```bash
npm test -- playbackWorkspaceNavigation.test.ts
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement wall-clock actions**

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

- [ ] **Step 4: Run GREEN**

```bash
npm test -- playbackWorkspaceNavigation.test.ts playbackTimelineV3.test.ts playbackTimelineV3.interaction.test.ts
```

Expected: PASS.

- [ ] **Step 5: Implement native `PlaybackWorkspace.vue` state**

Replace the Task 1 wrapper. Use:

```ts
const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const playerRef = ref<PlaybackPlayerHandle | null>(null)
const recordings = ref<RecordingItem[]>([])
const selectedCamera = ref<number | null>(null)
const selectedDate = ref(todayString())
const activeRecordingId = ref<number | null>(null)
const activeWallSeconds = ref<number | null>(null)
```

Load cameras and `/api/recordings/browser` using `selectedCamera` and `selectedDate`. Reuse the current recent-recording initialization request from `RecordingManagementView.vue` when route query is incomplete. Validate a deep-linked `recording_id` with `resolvePlaybackSelection()`.

Normalize Playback route state with:

```ts
function syncPlaybackRoute(recordingId: number | null = activeRecordingId.value) {
  const query: Record<string, string> = {}
  if (selectedCamera.value) query.camera_id = String(selectedCamera.value)
  if (selectedDate.value) query.date = selectedDate.value
  if (recordingId) query.recording_id = String(recordingId)
  void router.replace({ path: '/recordings/playback', query })
}
```

- [ ] **Step 6: Implement seek without DOM discovery or remounts**

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

- [ ] **Step 7: Feed video time back into the timeline**

```ts
function handlePlayerTime(seconds: number) {
  const recording = recordings.value.find((item) => item.id === activeRecordingId.value)
  const start = recording ? wallClockSeconds(recording.started_at) : null
  if (start === null) return
  activeWallSeconds.value = Math.max(0, Math.min(86400, start + Math.max(0, seconds)))
}
```

- [ ] **Step 8: Render only Playback information architecture**

Use this hierarchy:

```vue
<section class="playback-workspace">
  <header class="playback-context-bar">
    <el-select v-model="selectedCamera" class="playback-camera-select" />
    <el-date-picker v-model="selectedDate" type="date" value-format="YYYY-MM-DD" />
    <el-button @click="openManagement">管理当前录像</el-button>
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

Populate the `el-select` with `cameraStore` camera options. Do not include `el-table`, batch selection, delete controls, management calendar, storage filter, health filter, or upload filter.

- [ ] **Step 9: Implement Playback -> Management navigation**

```ts
function openManagement() {
  const query: Record<string, string> = {}
  if (selectedCamera.value) query.camera_id = String(selectedCamera.value)
  if (selectedDate.value) query.date = selectedDate.value
  if (activeRecordingId.value) query.recording_id = String(activeRecordingId.value)
  void router.push({ path: '/recordings/manage', query })
}
```

- [ ] **Step 10: Delete the bridge and verify**

```bash
git rm src/RecordingManagementWorkspace.vue
npm test
npm run build
```

Expected: PASS. Playback no longer imports or references `MutationObserver`, document-level `.recording-center .player-box video`, Teleport targets, or `viewKey`.

- [ ] **Step 11: Commit**

```bash
git add src/PlaybackWorkspace.vue src/PlaybackEventFeed.vue src/PlaybackTimelineV3.vue src/utils/playbackWorkspaceNavigation.ts src/playbackWorkspaceNavigation.test.ts
git commit -m "feat: make playback v3 a native workspace"
```

---

### Task 4: Preserve Management and add bidirectional deep links

**Files:**
- Create: `frontend/src/utils/recordingDeepLinks.ts`
- Create: `frontend/src/recordingDeepLinks.test.ts`
- Modify: `frontend/src/RecordingManagementView.vue`
- Modify: `frontend/src/PreviewView.vue`
- Modify: `frontend/src/EventCenterView.vue`
- Modify: `frontend/src/UploadManagementView.vue`
- Modify: `frontend/src/WorkspaceRoute.vue`

**Interfaces:**
- Viewing intent -> `/recordings/playback`.
- Segment/archive/compatibility administration -> `/recordings/manage`.

- [ ] **Step 1: Write RED deep-link tests**

Create `frontend/src/recordingDeepLinks.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { playbackLocationForRecording, managementLocationForContext } from './utils/recordingDeepLinks'

const recording = {
  id: 91,
  camera_id: 7,
  started_at: '2026-09-13T16:20:00+08:00',
  status: 'completed',
  health_status: 'healthy',
  upload_status: 'success',
  warning_count: 0,
  filename: '91.mp4',
  playback: { state: 'direct' as const, direct: true },
}

describe('recording deep links', () => {
  it('opens a managed recording in Playback', () => {
    expect(playbackLocationForRecording(recording)).toEqual({
      path: '/recordings/playback',
      query: { camera_id: '7', date: '2026-09-13', recording_id: '91' },
    })
  })

  it('opens Management without inventing a recording id', () => {
    expect(managementLocationForContext(7, '2026-09-13', null)).toEqual({
      path: '/recordings/manage',
      query: { camera_id: '7', date: '2026-09-13' },
    })
  })
})
```

- [ ] **Step 2: Run RED**

```bash
npm test -- recordingDeepLinks.test.ts
```

Expected: FAIL because the helper is missing.

- [ ] **Step 3: Implement deep-link helpers**

Create `frontend/src/utils/recordingDeepLinks.ts`:

```ts
import type { RouteLocationRaw } from 'vue-router'
import type { RecordingItem } from '../types/recordings'

function dateOf(value?: string | null) {
  return value && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null
}

export function playbackLocationForRecording(recording: RecordingItem): RouteLocationRaw {
  const query: Record<string, string> = {
    camera_id: String(recording.camera_id),
    recording_id: String(recording.id),
  }
  const date = dateOf(recording.started_at)
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

- [ ] **Step 4: Run GREEN**

```bash
npm test -- recordingDeepLinks.test.ts
```

Expected: PASS.

- [ ] **Step 5: Change Management playback navigation only, not management capabilities**

Keep single-click table selection. Double-click and explicit “回放” use:

```ts
function openInPlayback(item: RecordingItem) {
  void router.push(playbackLocationForRecording(item))
}
```

Keep the compatibility action local to Management:

```ts
async function openCompatibility(item: RecordingItem) {
  activeRecording.value = item
  await nextTick()
  await playerRef.value?.open(item, { forceCompatibility: true })
}
```

Do not remove the segment table, filters, calendar, selection, deletion, cloud/local status, upload status, health data or metadata.

- [ ] **Step 6: Route other product entry points by intent**

`PreviewView.vue`:

```ts
function openPlayback(cameraId: number | null) {
  const query = cameraId ? { camera_id: String(cameraId) } : undefined
  void router.push({ path: '/recordings/playback', query })
}
```

Use `@click="openPlayback(slot.cameraId)"`.

In `EventCenterView.vue`, actions whose meaning is “查看录像/回放” target `/recordings/playback` and preserve known camera/date/recording context.

`UploadManagementView.vue` administration links remain `/recordings/manage`.

`WorkspaceRoute.vue` compatibility/health operational link remains `/recordings/manage#playback-compatibility`.

- [ ] **Step 7: Search stale consumers and verify**

```bash
grep -R "recordings/browser" src && exit 1 || true
grep -R "recordings/manage" src
npm test
npm run build
```

Review every `recordings/manage` result: it must be a tab switch or an administration/compatibility action. Viewing actions must use `/recordings/playback`.

- [ ] **Step 8: Commit**

```bash
git add src/RecordingManagementView.vue src/PreviewView.vue src/EventCenterView.vue src/UploadManagementView.vue src/WorkspaceRoute.vue src/utils/recordingDeepLinks.ts src/recordingDeepLinks.test.ts
git commit -m "feat: link playback and recording management"
```

---

### Task 5: Remove hybrid-layout residue and run full acceptance verification

**Files:**
- Modify: `frontend/src/styles/recording-management.css` only where old cross-workspace selectors remain
- Modify: `docs/superpowers/specs/2026-09-13-playback-v3-design.md`
- Verify: `.github/workflows/ci.yml`

**Interfaces:**
- Final architecture: `RecordingsWorkspace` -> `PlaybackWorkspace` or `RecordingManagementView`.

- [ ] **Step 1: Remove old injection CSS**

Delete rules that existed only for the old bridge, including equivalents of:

```css
.recording-center .heat-section { display: none !important; }
.recording-center .recording-layout > .playback-v3 { grid-column: 1 / -1; }
.recording-center .catalog-column > .playback-event-feed { order: -1; }
```

Management may keep its own heat map; Playback owns its own timeline directly.

- [ ] **Step 2: Mark old design text as superseded**

Add near the top of `docs/superpowers/specs/2026-09-13-playback-v3-design.md`:

```md
> Architecture update: the “right-side catalog remains secondary” layout and the `RecordingManagementWorkspace` compatibility bridge are superseded by `2026-09-13-recordings-workspace-split-design.md`. Timeline math, wall-clock semantics, Motion behavior, and playback fallback requirements remain in force.
```

- [ ] **Step 3: Run source-structure checks**

From repository root:

```bash
! test -f frontend/src/RecordingManagementWorkspace.vue
grep -R "recording-center .player-box video" frontend/src && exit 1 || true
grep -R "to=\".recording-center" frontend/src && exit 1 || true
```

Expected: bridge file absent and no Playback-specific global DOM injection selectors.

- [ ] **Step 4: Run frontend verification**

```bash
cd frontend
npm test
npm run build
```

Expected: all Vitest tests PASS; `vue-tsc --noEmit` and Vite build PASS.

- [ ] **Step 5: Run backend regression verification**

From repository root:

```bash
uv run python -m compileall app
uv run python -m pytest
```

Expected: PASS.

- [ ] **Step 6: Acceptance-check the built UX**

Verify these exact cases:

```text
/recordings/playback -> 回放 tab active; no segment table or management filters
/recordings/manage -> 录像管理 tab active; full segment administration remains
/recordings/browser?camera_id=7&date=2026-09-13 -> redirects to Playback with query preserved
Tab switch -> camera_id/date/recording_id preserved
Management double-click -> matching recording opens in Playback
Playback “管理当前录像” -> matching context opens in Management
Same-recording timeline/event seek -> in-place player seek; workspace remains mounted
Cross-recording seek -> source changes and requested segment offset is applied
Gap click -> current source stays unchanged and “该时间没有可播放录像” appears
Repeated event click -> timeline remains mounted
Direct HEVC/H.264, H.264 compatibility proxy/live proxy, and cloud/OpenList playback retain existing fallback behavior
```

- [ ] **Step 7: Require final CI green on one SHA**

Do not declare completion until `frontend`, `backend`, and `docker-smoke` all report success for the same final commit.

- [ ] **Step 8: Commit cleanup**

```bash
git add frontend/src frontend/src/styles/recording-management.css docs/superpowers/specs/2026-09-13-playback-v3-design.md
git commit -m "cleanup: finish recordings workspace split"
```

- [ ] **Step 9: Deployment handoff**

After final CI is green, the deployment command is exactly:

```bash
git pull && ./deploy.sh
```

Do not require `docker image prune -f`.
