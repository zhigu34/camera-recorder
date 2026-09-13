<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import PlaybackTimelineV3 from './PlaybackTimelineV3.vue'
import RecordingManagementView from './RecordingManagementView.vue'
import { cameraIdFromRouteQuery } from './utils/cameraMotionPortal'
import {
  findRecordingAtWallTime,
  recordingSeekOffset,
  wallClockSeconds,
  type TimelineRecording,
} from './utils/playbackTimelineV3'

interface BrowserResult {
  items: TimelineRecording[]
}

interface PendingSeek {
  token: number
  recordingId: number
  seconds: number
}

const route = useRoute()
const router = useRouter()
const viewKey = ref(0)
const recordings = ref<TimelineRecording[]>([])
const timelineTargetReady = ref(false)
const activeWallSeconds = ref<number | null>(null)
const pendingSeek = ref<PendingSeek | null>(null)
const appliedSignatures = new WeakMap<HTMLVideoElement, string>()
let observer: MutationObserver | null = null
let observedVideo: HTMLVideoElement | null = null
let seekToken = 0

const cameraId = computed(() => cameraIdFromRouteQuery(route.query.camera_id))
const selectedDate = computed(() => {
  const raw = Array.isArray(route.query.date) ? route.query.date[0] : route.query.date
  return typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : null
})

function recordingIdFromRoute() {
  return cameraIdFromRouteQuery(route.query.recording_id)
}

function activeRecording() {
  const id = recordingIdFromRoute()
  return id ? recordings.value.find((item) => item.id === id) || null : null
}

function syncVideoClock(video: HTMLVideoElement) {
  const recording = activeRecording()
  const start = recording ? wallClockSeconds(recording.started_at) : null
  if (start === null) return
  activeWallSeconds.value = Math.max(0, Math.min(86400, start + Math.max(0, Number(video.currentTime || 0))))
}

function observeVideo(video: HTMLVideoElement | null) {
  if (observedVideo === video) return
  if (observedVideo) observedVideo.removeEventListener('timeupdate', handleVideoTimeUpdate)
  observedVideo = video
  if (observedVideo) observedVideo.addEventListener('timeupdate', handleVideoTimeUpdate, { passive: true })
}

function handleVideoTimeUpdate(event: Event) {
  if (event.currentTarget instanceof HTMLVideoElement) syncVideoClock(event.currentTarget)
}

function bindSeek(video: HTMLVideoElement, pending: PendingSeek) {
  const signature = `${pending.token}:${video.getAttribute('src') || video.currentSrc || ''}`
  if (appliedSignatures.get(video) === signature) return
  appliedSignatures.set(video, signature)

  const apply = () => {
    const current = pendingSeek.value
    if (!current || current.token !== pending.token) return
    const finiteDuration = Number.isFinite(video.duration) && video.duration > 0
    const maximum = finiteDuration ? Math.max(0, video.duration - 0.1) : current.seconds
    try {
      video.currentTime = Math.min(current.seconds, maximum)
    } catch {
      return
    }
    syncVideoClock(video)
    void video.play().catch(() => undefined)
  }

  if (video.readyState >= 1) apply()
  else video.addEventListener('loadedmetadata', apply, { once: true })

  video.addEventListener('playing', () => {
    const current = pendingSeek.value
    if (!current || current.token !== pending.token) return
    if (Math.abs(video.currentTime - current.seconds) <= 3) pendingSeek.value = null
  }, { once: true })
}

function refreshTargets() {
  timelineTargetReady.value = Boolean(document.querySelector('.recording-center .recording-layout'))
  const video = document.querySelector<HTMLVideoElement>('.recording-center .player-box video')
  observeVideo(video)
  const pending = pendingSeek.value
  if (video && pending) bindSeek(video, pending)
}

async function loadBrowser() {
  if (!cameraId.value || !selectedDate.value) {
    recordings.value = []
    return
  }
  try {
    const { data } = await axios.get<BrowserResult>('/api/recordings/browser', {
      params: { camera_id: cameraId.value, date: selectedDate.value },
    })
    recordings.value = data.items
    const current = activeRecording()
    const start = current ? wallClockSeconds(current.started_at) : null
    if (start !== null && activeWallSeconds.value === null) activeWallSeconds.value = start
  } catch {
    recordings.value = []
  }
}

async function handleTimelineSeek(wallSeconds: number) {
  const recording = findRecordingAtWallTime(recordings.value, wallSeconds)
  if (!recording?.started_at) {
    ElMessage.info('该时间没有可播放录像')
    return
  }

  activeWallSeconds.value = wallSeconds
  pendingSeek.value = {
    token: ++seekToken,
    recordingId: recording.id,
    seconds: recordingSeekOffset(recording, wallSeconds),
  }
  timelineTargetReady.value = false

  await router.replace({
    path: route.path,
    query: {
      ...route.query,
      camera_id: String(cameraId.value || ''),
      date: selectedDate.value || '',
      recording_id: String(recording.id),
    },
    hash: route.hash,
  })
  viewKey.value += 1
  await nextTick()
  refreshTargets()
}

watch(() => [route.query.camera_id, route.query.date] as const, async () => {
  activeWallSeconds.value = null
  timelineTargetReady.value = false
  await loadBrowser()
  await nextTick()
  refreshTargets()
})

watch(() => route.query.recording_id, () => {
  const pending = pendingSeek.value
  if (pending && recordingIdFromRoute() !== pending.recordingId) pendingSeek.value = null
  const current = activeRecording()
  const start = current ? wallClockSeconds(current.started_at) : null
  if (start !== null && !pendingSeek.value) activeWallSeconds.value = start
})

onMounted(async () => {
  observer = new MutationObserver(refreshTargets)
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['src'],
  })
  await loadBrowser()
  await nextTick()
  refreshTargets()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  observeVideo(null)
  pendingSeek.value = null
})
</script>

<template>
  <RecordingManagementView :key="viewKey" />

  <Teleport
    v-if="cameraId && selectedDate && timelineTargetReady"
    to=".recording-center .recording-layout"
  >
    <PlaybackTimelineV3
      :camera-id="cameraId"
      :date="selectedDate"
      :recordings="recordings"
      :active-wall-seconds="activeWallSeconds"
      @seek="handleTimelineSeek"
    />
  </Teleport>
</template>

<style>
.recording-center .heat-section {
  display: none !important;
}

.recording-center .recording-layout > .playback-v3 {
  grid-column: 1 / -1;
  min-width: 0;
  border: 1px solid var(--nvr-border);
  border-radius: 10px;
  background: var(--nvr-surface);
}
</style>
