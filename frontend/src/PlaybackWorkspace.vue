<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import PlaybackEventFeed from './PlaybackEventFeed.vue'
import PlaybackPlayer from './PlaybackPlayer.vue'
import PlaybackTimelineV3 from './PlaybackTimelineV3.vue'
import { useCameraStore } from './stores/cameras'
import type { BrowserResult, PlaybackPlayerHandle, RecordingItem } from './types/recordings'
import { wallClockSeconds } from './utils/playbackTimelineV3'
import {
  playbackWallClockAction,
  resolvePlaybackSelection,
} from './utils/playbackWorkspaceNavigation'

interface RecentRecording {
  id: number
  camera_id: number
  started_at?: string | null
}

const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const { cameras } = storeToRefs(cameraStore)

const playerRef = ref<PlaybackPlayerHandle | null>(null)
const recordings = ref<RecordingItem[]>([])
const selectedCamera = ref<number | null>(null)
const selectedDate = ref(todayString())
const activeRecordingId = ref<number | null>(null)
const activeWallSeconds = ref<number | null>(null)
const loading = ref(false)
const initialized = ref(false)
let routeSyncing = false

const activeRecording = computed(() => recordings.value.find((item) => item.id === activeRecordingId.value) || null)
const currentCameraName = computed(() => cameras.value.find((item) => item.id === selectedCamera.value)?.name || '未选择摄像头')
const activeClock = computed(() => {
  const seconds = activeWallSeconds.value
  if (seconds === null) return '--:--:--'
  const value = Math.max(0, Math.min(86399, Math.floor(seconds)))
  const h = Math.floor(value / 3600)
  const m = Math.floor((value % 3600) / 60)
  const s = value % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function queryValue(value: unknown) {
  return Array.isArray(value) ? value[0] : value
}

function positiveQueryInt(value: unknown) {
  const parsed = Number(queryValue(value) || 0)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function routeDate() {
  const value = queryValue(route.query.date)
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null
}

function recordingDate(value?: string | null) {
  return value && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null
}

function syncPlaybackRoute(recordingId: number | null = activeRecordingId.value) {
  const query: Record<string, string> = {}
  if (selectedCamera.value) query.camera_id = String(selectedCamera.value)
  if (selectedDate.value) query.date = selectedDate.value
  if (recordingId) query.recording_id = String(recordingId)
  routeSyncing = true
  void router.replace({ path: '/recordings/playback', query }).finally(() => {
    routeSyncing = false
  })
}

async function fetchDay() {
  if (!selectedCamera.value || !selectedDate.value) {
    recordings.value = []
    return
  }
  const { data } = await axios.get<BrowserResult>('/api/recordings/browser', {
    params: { camera_id: selectedCamera.value, date: selectedDate.value },
  })
  recordings.value = data.items
}

async function openSelection(recording: RecordingItem | null, seekSeconds = 0) {
  activeRecordingId.value = recording?.id || null
  if (!recording) {
    activeWallSeconds.value = null
    syncPlaybackRoute(null)
    return
  }
  const start = wallClockSeconds(recording.started_at)
  activeWallSeconds.value = start === null ? null : Math.max(0, Math.min(86400, start + seekSeconds))
  syncPlaybackRoute(recording.id)
  await nextTick()
  await playerRef.value?.open(recording, { seekSeconds })
}

async function loadContext(preferredRecordingId: number | null = activeRecordingId.value) {
  if (!selectedCamera.value || !selectedDate.value) return
  loading.value = true
  try {
    await fetchDay()
    const selected = resolvePlaybackSelection(recordings.value, preferredRecordingId) as RecordingItem | null
    await openSelection(selected)
  } catch (error) {
    recordings.value = []
    activeRecordingId.value = null
    activeWallSeconds.value = null
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '回放录像加载失败')
  } finally {
    loading.value = false
  }
}

async function initialize() {
  loading.value = true
  try {
    await cameraStore.load()
    const deepCamera = positiveQueryInt(route.query.camera_id)
    const deepRecording = positiveQueryInt(route.query.recording_id)
    const deepDate = routeDate()
    const validDeepCamera = deepCamera && cameras.value.some((item) => item.id === deepCamera) ? deepCamera : null

    if (validDeepCamera) {
      selectedCamera.value = validDeepCamera
      selectedDate.value = deepDate || todayString()
    } else {
      const { data } = await axios.get<RecentRecording[]>('/api/recordings?limit=1')
      const latest = data[0] || null
      if (latest && cameras.value.some((item) => item.id === latest.camera_id)) {
        selectedCamera.value = latest.camera_id
        selectedDate.value = recordingDate(latest.started_at) || todayString()
      } else if (cameras.value.length) {
        selectedCamera.value = cameras.value[0].id
        selectedDate.value = deepDate || todayString()
      }
    }

    if (selectedCamera.value) {
      await fetchDay()
      const selected = resolvePlaybackSelection(recordings.value, deepRecording) as RecordingItem | null
      await openSelection(selected)
    }
    initialized.value = true
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '回放初始化失败')
  } finally {
    loading.value = false
  }
}

async function handleCameraChange() {
  activeRecordingId.value = null
  activeWallSeconds.value = null
  await loadContext(null)
}

async function handleDateChange() {
  if (!selectedDate.value) return
  activeRecordingId.value = null
  activeWallSeconds.value = null
  await loadContext(null)
}

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

function handlePlayerTime(seconds: number) {
  const recording = activeRecording.value
  const start = recording ? wallClockSeconds(recording.started_at) : null
  if (start === null) return
  activeWallSeconds.value = Math.max(0, Math.min(86400, start + Math.max(0, seconds)))
}

async function handlePlayerEnded() {
  const currentIndex = recordings.value.findIndex((item) => item.id === activeRecordingId.value)
  if (currentIndex < 0) return
  const next = recordings.value.slice(currentIndex + 1).find((item) => Boolean(
    item.playback?.original_available
    || item.playback?.remote_available
    || item.playback?.state === 'ready'
    || item.playback?.cloud_state === 'ready',
  ))
  if (next) await openSelection(next)
}

function openManagement() {
  const query: Record<string, string> = {}
  if (selectedCamera.value) query.camera_id = String(selectedCamera.value)
  if (selectedDate.value) query.date = selectedDate.value
  if (activeRecordingId.value) query.recording_id = String(activeRecordingId.value)
  void router.push({ path: '/recordings/manage', query })
}

watch(
  () => [route.query.camera_id, route.query.date, route.query.recording_id] as const,
  async () => {
    if (!initialized.value || routeSyncing || route.path !== '/recordings/playback') return
    const cameraId = positiveQueryInt(route.query.camera_id)
    const date = routeDate()
    const recordingId = positiveQueryInt(route.query.recording_id)
    const changedContext = cameraId !== selectedCamera.value || (date && date !== selectedDate.value)
    if (!changedContext && recordingId === activeRecordingId.value) return
    if (cameraId && cameras.value.some((item) => item.id === cameraId)) selectedCamera.value = cameraId
    if (date) selectedDate.value = date
    await loadContext(recordingId)
  },
)

onMounted(() => void initialize())
</script>

<template>
  <section class="playback-workspace" v-loading="loading">
    <header class="playback-context-bar">
      <div class="context-controls">
        <el-select
          v-model="selectedCamera"
          filterable
          placeholder="选择摄像头"
          class="playback-camera-select"
          @change="handleCameraChange"
        >
          <el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" />
        </el-select>
        <el-date-picker
          v-model="selectedDate"
          type="date"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          class="playback-date-picker"
          @change="handleDateChange"
        />
      </div>
      <div class="context-status">
        <span>{{ currentCameraName }}</span>
        <strong>{{ activeClock }}</strong>
        <el-button size="small" @click="openManagement">管理当前录像</el-button>
      </div>
    </header>

    <div class="playback-main-grid">
      <section class="playback-video-panel">
        <div class="playback-video-meta">
          <div><strong>{{ currentCameraName }}</strong><span>{{ selectedDate }}</span></div>
          <span v-if="activeRecording">{{ activeRecording.filename }}</span>
        </div>
        <PlaybackPlayer
          ref="playerRef"
          @timeupdate="handlePlayerTime"
          @ended="handlePlayerEnded"
        />
      </section>

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
</template>

<style scoped>
.playback-workspace{min-width:0;max-width:1840px;margin:0 auto;padding:12px 18px 26px}.playback-context-bar{min-height:46px;display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;padding:6px 8px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.context-controls,.context-status{display:flex;align-items:center;gap:7px;min-width:0}.playback-camera-select{width:210px}.playback-date-picker{width:150px!important}.context-status{color:var(--nvr-muted);font-size:9px}.context-status>span{max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.context-status>strong{color:var(--nvr-text);font-size:13px;font-variant-numeric:tabular-nums;letter-spacing:.03em}.playback-main-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(285px,340px);gap:10px;align-items:stretch}.playback-video-panel{min-width:0;padding:10px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.playback-video-meta{height:30px;display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:0 2px}.playback-video-meta>div{display:flex;align-items:baseline;gap:8px;min-width:0}.playback-video-meta strong{font-size:11px}.playback-video-meta span{max-width:46%;overflow:hidden;color:var(--nvr-subtle);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.playback-workspace :deep(.playback-v3){margin-top:10px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.playback-workspace :deep(.playback-event-feed){min-width:0;height:100%}
@media(max-width:1100px){.playback-main-grid{grid-template-columns:1fr}.playback-workspace :deep(.playback-event-feed){max-height:430px}.context-status>span{display:none}}
@media(max-width:700px){.playback-workspace{padding:8px}.playback-context-bar{align-items:stretch;flex-direction:column}.context-controls{display:grid;grid-template-columns:1fr 1fr}.playback-camera-select,.playback-date-picker{width:100%!important}.context-status{justify-content:space-between}.playback-main-grid{gap:8px}}
</style>
