<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import MotionTimelineTrack from './MotionTimelineTrack.vue'
import RecordingManagementView from './RecordingManagementView.vue'
import { cameraIdFromRouteQuery } from './utils/cameraMotionPortal'
import { eventSeekOffset, findMotionRecording } from './utils/motionTimeline'

interface MotionEventItem {
  id: number
  camera_id: number
  recording_id?: number | null
  started_at: string
  ended_at: string
}

interface RecordingItem {
  id: number
  camera_id: number
  started_at?: string | null
  ended_at?: string | null
  duration?: number | null
}

interface BrowserResult {
  items: RecordingItem[]
}

interface PendingSeek {
  token: number
  recordingId: number
  seconds: number
}

const route = useRoute()
const router = useRouter()
const viewKey = ref(0)
const timelineTargetReady = ref(false)
const pendingSeek = ref<PendingSeek | null>(null)
const appliedSignatures = new WeakMap<HTMLVideoElement, string>()
let observer: MutationObserver | null = null
let seekToken = 0

const cameraId = computed(() => cameraIdFromRouteQuery(route.query.camera_id))
const selectedDate = computed(() => {
  const raw = Array.isArray(route.query.date) ? route.query.date[0] : route.query.date
  return typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : null
})

function recordingIdFromRoute() {
  return cameraIdFromRouteQuery(route.query.recording_id)
}

function refreshTargets() {
  timelineTargetReady.value = Boolean(document.querySelector('.recording-center .heat-section'))
  applyPendingSeek()
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

function applyPendingSeek() {
  const pending = pendingSeek.value
  if (!pending) return
  const video = document.querySelector<HTMLVideoElement>('.recording-center .player-box video')
  if (video) bindSeek(video, pending)
}

async function loadRecordingForEvent(event: MotionEventItem) {
  if (!cameraId.value || !selectedDate.value) return null
  const browser = await axios.get<BrowserResult>('/api/recordings/browser', {
    params: { camera_id: cameraId.value, date: selectedDate.value },
  })
  let recording = findMotionRecording(event, browser.data.items)
  if (recording || !event.recording_id) return recording

  const recent = await axios.get<RecordingItem[]>('/api/recordings', {
    params: { camera_id: cameraId.value, limit: 1000 },
  })
  recording = findMotionRecording(event, recent.data)
  return recording
}

async function openMotionEvent(event: MotionEventItem) {
  if (!cameraId.value || !selectedDate.value) return
  try {
    const recording = await loadRecordingForEvent(event)
    if (!recording?.started_at) {
      ElMessage.warning('该移动事件没有可播放的录像片段')
      return
    }

    const targetDate = recording.started_at.slice(0, 10)
    const pending: PendingSeek = {
      token: ++seekToken,
      recordingId: recording.id,
      seconds: eventSeekOffset(event.started_at, recording.started_at),
    }
    pendingSeek.value = pending
    timelineTargetReady.value = false

    await router.replace({
      path: route.path,
      query: {
        ...route.query,
        camera_id: String(cameraId.value),
        date: targetDate,
        recording_id: String(recording.id),
      },
      hash: route.hash,
    })
    viewKey.value += 1
    await nextTick()
    refreshTargets()
  } catch (error) {
    const detail = axios.isAxiosError(error) ? error.response?.data?.detail || error.message : null
    ElMessage.error(typeof detail === 'string' && detail ? detail : '移动事件定位失败')
  }
}

watch(() => [route.query.camera_id, route.query.date] as const, async () => {
  timelineTargetReady.value = false
  await nextTick()
  refreshTargets()
})

watch(() => route.query.recording_id, () => {
  const pending = pendingSeek.value
  if (pending && recordingIdFromRoute() !== pending.recordingId) pendingSeek.value = null
})

onMounted(() => {
  observer = new MutationObserver(refreshTargets)
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['src'],
  })
  refreshTargets()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  pendingSeek.value = null
})
</script>

<template>
  <RecordingManagementView :key="viewKey" />

  <Teleport
    v-if="cameraId && selectedDate && timelineTargetReady"
    to=".recording-center .heat-section"
  >
    <MotionTimelineTrack
      :camera-id="cameraId"
      :date="selectedDate"
      @select="openMotionEvent"
    />
  </Teleport>
</template>
