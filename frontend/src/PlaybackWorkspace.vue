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
import type { SharedCamera } from './stores/cameras'
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

function cameraStatusClass(camera: SharedCamera) {
  if (!camera.enabled) return 'unknown'
  if (camera.connectivity_status === 'online') return 'online'
  if (camera.connectivity_status === 'offline') return 'offline'
  return 'unknown'
}

function cameraStatusLabel(camera: SharedCamera) {
  if (!camera.enabled) return '未启用'
  if (camera.connectivity_status === 'online') return '在线'
  if (camera.connectivity_status === 'offline') return '离线'
  return '状态未知'
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

function updateSelectionState(recording: RecordingItem | null, seekSeconds = 0) {
  activeRecordingId.value = recording?.id || null
  if (!recording) {
    activeWallSeconds.value = null
    syncPlaybackRoute(null)
    return
  }
  const start = wallClockSeconds(recording.started_at)
  activeWallSeconds.value = start === null ? null : Math.max(0, Math.min(86400, start + seekSeconds))
  syncPlaybackRoute(recording.id)
}

async function selectSelection(recording: RecordingItem | null, seekSeconds = 0) {
  updateSelectionState(recording, seekSeconds)
  await nextTick()
  playerRef.value?.select(recording, { seekSeconds })
}

async function openSelection(recording: RecordingItem | null, seekSeconds = 0) {
  updateSelectionState(recording, seekSeconds)
  await nextTick()
  if (!recording) {
    playerRef.value?.select(null)
    return
  }
  await playerRef.value?.open(recording, { seekSeconds })
}

async function loadContext(preferredRecordingId: number | null = activeRecordingId.value) {
  if (!selectedCamera.value || !selectedDate.value) return
  loading.value = true
  try {
    await fetchDay()
    const selected = resolvePlaybackSelection(recordings.value, preferredRecordingId) as RecordingItem | null
    await selectSelection(selected)
  } catch (error) {
    recordings.value = []
    activeRecordingId.value = null
    activeWallSeconds.value = null
    await nextTick()
    playerRef.value?.select(null)
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
      await selectSelection(selected)
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

async function selectCamera(cameraId: number) {
  if (selectedCamera.value === cameraId) return
  selectedCamera.value = cameraId
  await handleCameraChange()
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
    <div class="playback-main-grid">
      <div class="playback-side-slot playback-left-slot">
        <aside class="playback-sidebar">
          <div class="playback-sidebar-section playback-date-section">
            <div class="playback-sidebar-label">日期</div>
            <el-date-picker
              v-model="selectedDate"
              type="date"
              value-format="YYYY-MM-DD"
              format="YYYY-MM-DD"
              class="playback-date-picker"
              @change="handleDateChange"
            />
          </div>

          <div class="playback-sidebar-divider"></div>

          <div class="playback-camera-head">
            <strong>摄像头</strong>
            <span>{{ cameras.length }}</span>
          </div>
          <div class="playback-camera-list">
            <button
              v-for="camera in cameras"
              :key="camera.id"
              type="button"
              class="playback-camera-row"
              :class="{ active: selectedCamera === camera.id }"
              @click="selectCamera(camera.id)"
            >
              <span
                class="camera-status-dot"
                :class="cameraStatusClass(camera)"
                :title="cameraStatusLabel(camera)"
              ></span>
              <span class="camera-name">{{ camera.name }}</span>
            </button>
          </div>
        </aside>
      </div>

      <section class="playback-video-panel">
        <div class="playback-video-meta">
          <div class="playback-video-title">
            <strong>{{ currentCameraName }}</strong>
            <span v-if="activeRecording">{{ activeRecording.filename }}</span>
            <span v-else>{{ selectedDate }}</span>
          </div>
          <div class="playback-video-actions">
            <strong class="playback-clock">{{ activeClock }}</strong>
            <el-button size="small" @click="openManagement">管理当前录像</el-button>
          </div>
        </div>
        <PlaybackPlayer
          ref="playerRef"
          @timeupdate="handlePlayerTime"
          @ended="handlePlayerEnded"
        />
      </section>

      <div class="playback-side-slot playback-events-slot">
        <PlaybackEventFeed
          v-if="selectedCamera"
          :camera-id="selectedCamera"
          :date="selectedDate"
          :recordings="recordings"
          :active-wall-seconds="activeWallSeconds"
          @seek="seekWallClock"
        />
      </div>
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
.playback-workspace{min-width:0;max-width:1840px;margin:0 auto;padding:12px 18px 26px;box-sizing:border-box}.playback-main-grid{display:grid;grid-template-columns:160px minmax(0,1fr) 280px;gap:10px;align-items:stretch}.playback-side-slot{position:relative;min-width:0;min-height:0}.playback-sidebar{min-width:0;overflow:hidden;display:flex;flex-direction:column;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.playback-sidebar-section{padding:12px}.playback-sidebar-label{margin-bottom:8px;color:var(--nvr-muted);font-size:9px;font-weight:700;letter-spacing:.06em}.playback-date-picker{width:100%!important;min-width:0}:deep(.playback-date-picker .el-input__wrapper){min-width:0;padding:0 7px}:deep(.playback-date-picker .el-input__inner){min-width:0;font-size:11px}.playback-sidebar-divider{height:1px;flex:none;background:var(--nvr-border)}.playback-camera-head{display:flex;align-items:center;justify-content:space-between;padding:11px 12px 7px}.playback-camera-head strong{font-size:10px}.playback-camera-head span{min-width:20px;padding:2px 6px;border-radius:999px;color:var(--nvr-subtle);background:var(--nvr-input);font-size:8px;text-align:center}.playback-camera-list{min-height:0;overflow:auto;padding:0 7px 9px;scrollbar-gutter:stable}.playback-camera-row{position:relative;width:100%;display:flex;align-items:center;gap:9px;padding:8px 9px;border:1px solid transparent;border-radius:7px;color:var(--nvr-muted);background:transparent;font:inherit;text-align:left;cursor:pointer}.playback-camera-row:hover{background:var(--nvr-hover);color:var(--nvr-text-soft)}.playback-camera-row.active{border-color:color-mix(in srgb,var(--nvr-blue) 44%,var(--nvr-border));color:var(--nvr-text);background:color-mix(in srgb,var(--nvr-blue) 10%,var(--nvr-input))}.playback-camera-row.active::before{content:'';position:absolute;left:-1px;top:7px;bottom:7px;width:2px;border-radius:2px;background:var(--nvr-blue)}.camera-status-dot{width:7px;height:7px;flex:none;border-radius:50%;background:#667386;box-shadow:0 0 0 3px rgba(102,115,134,.09)}.camera-status-dot.online{background:#38b66f;box-shadow:0 0 0 3px rgba(56,182,111,.11)}.camera-status-dot.offline{background:#d15858;box-shadow:0 0 0 3px rgba(209,88,88,.1)}.camera-name{min-width:0;overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.playback-video-panel{min-width:0;align-self:start;padding:10px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.playback-video-meta{min-height:34px;display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:0 2px}.playback-video-title{min-width:0;display:flex;align-items:baseline;gap:8px}.playback-video-title strong{flex:none;font-size:11px}.playback-video-title span{min-width:0;overflow:hidden;color:var(--nvr-subtle);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.playback-video-actions{flex:none;display:flex;align-items:center;gap:8px}.playback-clock{color:var(--nvr-text-soft);font-size:12px;font-variant-numeric:tabular-nums;letter-spacing:.03em}.playback-workspace :deep(.playback-v3){margin-top:10px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.playback-workspace :deep(.playback-event-feed){min-width:0;height:100%}
@media(min-width:1101px){.playback-workspace{display:block;overflow:visible;padding:10px 18px 12px}.playback-main-grid{min-height:0;overflow:hidden}.playback-left-slot>.playback-sidebar{position:absolute;inset:0}.playback-sidebar{min-height:0}.playback-camera-list{flex:1}.playback-workspace :deep(.playback-player .player-box){width:100%;aspect-ratio:16/9}.playback-events-slot :deep(.playback-event-feed){position:absolute;inset:0;min-height:0;display:flex;flex-direction:column}.playback-workspace :deep(.playback-event-feed .event-feed-body){max-height:none;min-height:0;flex:1}.playback-workspace :deep(.playback-v3){margin-top:8px}}
@media(max-width:1100px){.playback-main-grid{grid-template-columns:1fr}.playback-sidebar{max-height:340px}.playback-camera-list{max-height:220px}.playback-workspace :deep(.playback-event-feed){max-height:430px}}
@media(max-width:700px){.playback-workspace{padding:8px}.playback-main-grid{gap:8px}.playback-sidebar-section{padding:10px}.playback-video-meta{align-items:stretch;flex-direction:column;padding-bottom:8px}.playback-video-actions{justify-content:space-between}.playback-video-title span{max-width:64%}}
</style>