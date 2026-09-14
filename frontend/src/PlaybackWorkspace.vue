<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import PlaybackEventFeed from './PlaybackEventFeed.vue'
import PlaybackPlayer from './PlaybackPlayer.vue'
import PlaybackTimelineV3 from './PlaybackTimelineV3.vue'
import PlaybackTransportControls from './PlaybackTransportControls.vue'
import { useCameraStore } from './stores/cameras'
import type { SharedCamera } from './stores/cameras'
import type {
  ExportArtifact,
  ExportGapPolicy,
  ExportJob,
  ExportMode,
  ExportPackageMode,
  ExportRange,
  ExportRangeAnalysis,
} from './types/exports'
import type { BrowserResult, PlaybackPlayerHandle, RecordingItem } from './types/recordings'
import {
  availablePackageModes,
  buildExportRequest,
  initialExportRange,
} from './utils/playbackExport'
import {
  loadSkipInterval,
  normalizePlaybackRate,
  playbackSkipTarget,
  saveSkipInterval,
} from './utils/playbackTransport'
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

const PLAYBACK_EVENT_AUTOSTART_KEY = 'camera-recorder:playback-event-autostart'
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
const routeEventId = ref<number | null>(null)
const routeEventWallSeconds = ref<number | null>(null)
const routeEventPlayUntilSeconds = ref<number | null>(null)
const playbackRate = ref(1)
const skipSeconds = ref(loadSkipInterval(playbackStorage()))
const loading = ref(false)
const initialized = ref(false)
const rangeSelectEnabled = ref(false)
const exportRange = ref<ExportRange | null>(null)
const exportAnalysis = ref<ExportRangeAnalysis | null>(null)
const exportMode = ref<ExportMode>('fast')
const gapPolicy = ref<ExportGapPolicy>('merge')
const packageMode = ref<ExportPackageMode>('individual')
const analyzingExport = ref(false)
const creatingExport = ref(false)
const activeExportJob = ref<ExportJob | null>(null)
const exportArtifacts = ref<ExportArtifact[]>([])
let exportPollTimer: ReturnType<typeof setTimeout> | null = null
let routeSyncing = false

const activeRecording = computed(() => recordings.value.find((item) => item.id === activeRecordingId.value) || null)
const currentCameraName = computed(() => cameras.value.find((item) => item.id === selectedCamera.value)?.name || '未选择摄像头')
const activeClock = computed(() => {
  const seconds = activeWallSeconds.value
  if (seconds === null) return '--:--:--'
  return clockText(seconds)
})
const hasExportGaps = computed(() => Boolean(exportAnalysis.value?.gaps.length))
const packageModes = computed(() => availablePackageModes(gapPolicy.value, hasExportGaps.value))
const exportRangeLabel = computed(() => exportRange.value
  ? `${clockText(exportRange.value.start)} – ${clockText(exportRange.value.end)}`
  : '--:--:--')

function playbackStorage() {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function clockText(seconds: number) {
  const value = Math.max(0, Math.min(86400, Math.floor(seconds)))
  const h = Math.floor(value / 3600)
  const m = Math.floor((value % 3600) / 60)
  const s = value % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function isoClock(value?: string | null) {
  const seconds = wallClockSeconds(value)
  return seconds === null ? '--:--:--' : clockText(seconds)
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`
}

function queryValue(value: unknown) {
  return Array.isArray(value) ? value[0] : value
}

function positiveQueryInt(value: unknown) {
  const parsed = Number(queryValue(value) || 0)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function boundedRouteSeconds(value: unknown) {
  const parsed = Number(queryValue(value))
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 86400 ? parsed : null
}

function routeWallSeconds() {
  return boundedRouteSeconds(route.query.wall_seconds)
}

function routePlayUntilWallSeconds() {
  return boundedRouteSeconds(route.query.play_until_wall_seconds)
}

function routeDate() {
  const value = queryValue(route.query.date)
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null
}

function recordingDate(value?: string | null) {
  return value && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null
}

function consumePlaybackEventAutostart(eventId: number | null) {
  if (!eventId || typeof window === 'undefined') return false
  try {
    const stored = window.sessionStorage.getItem(PLAYBACK_EVENT_AUTOSTART_KEY)
    if (stored !== String(eventId)) return false
    window.sessionStorage.removeItem(PLAYBACK_EVENT_AUTOSTART_KEY)
    return true
  } catch {
    return false
  }
}

function clearEventRouteContext() {
  routeEventId.value = null
  routeEventWallSeconds.value = null
  routeEventPlayUntilSeconds.value = null
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

function stopExportPolling() {
  if (exportPollTimer !== null) {
    clearTimeout(exportPollTimer)
    exportPollTimer = null
  }
}

function resetExportContext() {
  stopExportPolling()
  rangeSelectEnabled.value = false
  exportRange.value = null
  exportAnalysis.value = null
  activeExportJob.value = null
  exportArtifacts.value = []
  exportMode.value = 'fast'
  gapPolicy.value = 'merge'
  packageMode.value = 'individual'
}

function syncPlaybackRoute(recordingId: number | null = activeRecordingId.value) {
  const query: Record<string, string> = {}
  if (selectedCamera.value) query.camera_id = String(selectedCamera.value)
  if (selectedDate.value) query.date = selectedDate.value
  if (recordingId) query.recording_id = String(recordingId)
  if (routeEventId.value) query.event_id = String(routeEventId.value)
  if (routeEventWallSeconds.value !== null) query.wall_seconds = String(routeEventWallSeconds.value)
  if (routeEventPlayUntilSeconds.value !== null) query.play_until_wall_seconds = String(routeEventPlayUntilSeconds.value)
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
    const deepEventId = positiveQueryInt(route.query.event_id)
    const deepWallSeconds = routeWallSeconds()
    const deepPlayUntilSeconds = routePlayUntilWallSeconds()
    const deepDate = routeDate()
    const validDeepCamera = deepCamera && cameras.value.some((item) => item.id === deepCamera) ? deepCamera : null
    const explicitEventAutostart = consumePlaybackEventAutostart(deepEventId)
    routeEventId.value = deepEventId
    routeEventWallSeconds.value = deepWallSeconds
    routeEventPlayUntilSeconds.value = deepPlayUntilSeconds

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
      if (deepWallSeconds !== null) {
        const action = playbackWallClockAction(deepRecording, recordings.value, deepWallSeconds)
        if (action.kind === 'seek') {
          const recording = recordings.value.find((item) => item.id === action.recordingId) || null
          if (explicitEventAutostart) await openSelection(recording, action.seekSeconds)
          else await selectSelection(recording, action.seekSeconds)
        } else {
          const selected = resolvePlaybackSelection(recordings.value, deepRecording) as RecordingItem | null
          if (explicitEventAutostart) await openSelection(selected)
          else await selectSelection(selected)
        }
      } else {
        const selected = resolvePlaybackSelection(recordings.value, deepRecording) as RecordingItem | null
        await selectSelection(selected)
      }
    }
    initialized.value = true
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '回放初始化失败')
  } finally {
    loading.value = false
  }
}

async function handleCameraChange() {
  resetExportContext()
  clearEventRouteContext()
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
  resetExportContext()
  clearEventRouteContext()
  activeRecordingId.value = null
  activeWallSeconds.value = null
  await loadContext(null)
}

async function seekWallClock(wallSeconds: number) {
  clearEventRouteContext()
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
    syncPlaybackRoute(recording.id)
    playerRef.value?.seek(action.seekSeconds)
    await playerRef.value?.play().catch(() => undefined)
  }
  activeWallSeconds.value = action.wallSeconds
}

function handlePlaybackRate(value: number) {
  playbackRate.value = normalizePlaybackRate(value)
}

function handleSkipSeconds(value: number) {
  skipSeconds.value = saveSkipInterval(value, playbackStorage())
}

async function skipPlayback(deltaSeconds: number) {
  const target = playbackSkipTarget(activeWallSeconds.value, deltaSeconds)
  if (target === null) return
  await seekWallClock(target)
}

function handlePlayerTime(seconds: number) {
  const recording = activeRecording.value
  const start = recording ? wallClockSeconds(recording.started_at) : null
  if (start === null) return
  const wallSeconds = Math.max(0, Math.min(86400, start + Math.max(0, seconds)))
  activeWallSeconds.value = wallSeconds
  if (routeEventPlayUntilSeconds.value !== null && wallSeconds >= routeEventPlayUntilSeconds.value) {
    routeEventPlayUntilSeconds.value = null
    playerRef.value?.pause()
    syncPlaybackRoute(activeRecordingId.value)
  }
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

function startExportRangeSelection() {
  if (!selectedCamera.value) return
  stopExportPolling()
  exportRange.value = initialExportRange(activeWallSeconds.value, recordings.value)
  exportAnalysis.value = null
  activeExportJob.value = null
  exportArtifacts.value = []
  exportMode.value = 'fast'
  gapPolicy.value = 'merge'
  packageMode.value = 'individual'
  rangeSelectEnabled.value = true
}

function cancelExportRangeSelection() {
  rangeSelectEnabled.value = false
  exportRange.value = null
  exportAnalysis.value = null
}

function handleExportRangeChange(range: ExportRange) {
  exportRange.value = { ...range }
  exportAnalysis.value = null
}

function handleExportRangeCommit(range: ExportRange) {
  exportRange.value = { ...range }
  exportAnalysis.value = null
}

async function analyzeExportSelection() {
  if (!selectedCamera.value || !exportRange.value) return
  analyzingExport.value = true
  try {
    const request = buildExportRequest({
      cameraId: selectedCamera.value,
      date: selectedDate.value,
      range: exportRange.value,
      exportMode: exportMode.value,
      gapPolicy: gapPolicy.value,
      packageMode: packageMode.value,
    })
    const { data } = await axios.post<ExportRangeAnalysis>('/api/exports/analyze', {
      camera_id: request.camera_id,
      start_at: request.start_at,
      end_at: request.end_at,
    })
    exportAnalysis.value = data
    gapPolicy.value = 'merge'
    packageMode.value = 'individual'
    if (!data.exportable) ElMessage.warning('所选范围没有可导出的本地录像')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '导出范围分析失败')
  } finally {
    analyzingExport.value = false
  }
}

function handleGapPolicyChange() {
  if (!packageModes.value.includes(packageMode.value)) packageMode.value = 'individual'
}

async function fetchExportArtifacts(jobId: number) {
  const { data } = await axios.get<ExportArtifact[]>(`/api/exports/${jobId}/artifacts`)
  if (activeExportJob.value?.id === jobId) exportArtifacts.value = data
}

function scheduleExportPoll(job: ExportJob) {
  stopExportPolling()
  if (job.status !== 'pending' && job.status !== 'processing') return
  exportPollTimer = setTimeout(() => void refreshExportJob(job.id), 1200)
}

async function refreshExportJob(jobId: number) {
  try {
    const { data: job } = await axios.get<ExportJob>(`/api/exports/${jobId}`)
    if (activeExportJob.value?.id !== jobId) return
    activeExportJob.value = job
    if (job.status === 'ready') {
      stopExportPolling()
      await fetchExportArtifacts(job.id)
      return
    }
    if (job.status === 'failed' || job.status === 'expired') {
      stopExportPolling()
      return
    }
    scheduleExportPoll(job)
  } catch (error) {
    stopExportPolling()
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '导出任务状态读取失败')
  }
}

async function createExportJob() {
  if (!selectedCamera.value || !exportRange.value || !exportAnalysis.value?.exportable) return
  creatingExport.value = true
  try {
    const request = buildExportRequest({
      cameraId: selectedCamera.value,
      date: selectedDate.value,
      range: exportRange.value,
      exportMode: exportMode.value,
      gapPolicy: gapPolicy.value,
      packageMode: packageMode.value,
    })
    const { data: job } = await axios.post<ExportJob>('/api/exports', request)
    activeExportJob.value = job
    exportArtifacts.value = []
    rangeSelectEnabled.value = false
    scheduleExportPoll(job)
    ElMessage.success('导出任务已创建')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '导出任务创建失败')
  } finally {
    creatingExport.value = false
  }
}

function downloadExportArtifact(artifact: ExportArtifact) {
  if (!activeExportJob.value) return
  const url = `/api/exports/${activeExportJob.value.id}/artifacts/${artifact.id}/download`
  window.open(url, '_blank', 'noopener,noreferrer')
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
    if (changedContext) resetExportContext()
    clearEventRouteContext()
    if (cameraId && cameras.value.some((item) => item.id === cameraId)) selectedCamera.value = cameraId
    if (date) selectedDate.value = date
    await loadContext(recordingId)
  },
)

onMounted(() => void initialize())
onBeforeUnmount(() => stopExportPolling())
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
            <el-button v-if="!rangeSelectEnabled" size="small" @click="startExportRangeSelection">导出片段</el-button>
            <el-button v-else size="small" type="primary" plain @click="cancelExportRangeSelection">取消导出</el-button>
            <el-button size="small" @click="openManagement">管理当前录像</el-button>
          </div>
        </div>
        <PlaybackPlayer
          ref="playerRef"
          :playback-rate="playbackRate"
          @timeupdate="handlePlayerTime"
          @ended="handlePlayerEnded"
        />
        <PlaybackTransportControls
          :active="activeWallSeconds !== null"
          :playback-rate="playbackRate"
          :skip-seconds="skipSeconds"
          @skip="skipPlayback"
          @update:playback-rate="handlePlaybackRate"
          @update:skip-seconds="handleSkipSeconds"
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

    <section v-if="rangeSelectEnabled && exportRange" class="playback-export-panel">
      <div class="export-panel-head">
        <div>
          <strong>导出范围</strong>
          <span>{{ exportRangeLabel }}</span>
        </div>
        <div class="export-panel-actions">
          <el-button size="small" @click="cancelExportRangeSelection">取消</el-button>
          <el-button size="small" type="primary" :loading="analyzingExport" @click="analyzeExportSelection">分析范围</el-button>
        </div>
      </div>

      <div v-if="exportAnalysis" class="export-analysis">
        <div class="export-stats">
          <span>录像 <strong>{{ exportAnalysis.recording_count }}</strong></span>
          <span>覆盖 <strong>{{ Math.round(exportAnalysis.covered_duration) }}s</strong></span>
          <span>缺口 <strong>{{ exportAnalysis.gaps.length }}</strong></span>
          <span v-if="exportAnalysis.unavailable_count">本地不可用 <strong>{{ exportAnalysis.unavailable_count }}</strong></span>
        </div>
        <div v-if="exportAnalysis.gaps.length" class="export-gap-list">
          <span v-for="(gap, index) in exportAnalysis.gaps.slice(0, 4)" :key="`${gap.start_at}-${index}`">
            {{ isoClock(gap.start_at) }}–{{ isoClock(gap.end_at) }} · {{ Math.round(gap.duration) }}s
          </span>
          <small v-if="exportAnalysis.gaps.length > 4">另有 {{ exportAnalysis.gaps.length - 4 }} 个缺口</small>
        </div>
        <div v-if="exportAnalysis.exportable" class="export-options">
          <label>
            <span>边界</span>
            <select v-model="exportMode">
              <option value="fast">快速 · 无损封装</option>
              <option value="exact">精确 · 重新编码</option>
            </select>
          </label>
          <label v-if="hasExportGaps">
            <span>缺口处理</span>
            <select v-model="gapPolicy" @change="handleGapPolicyChange">
              <option value="merge">合并为一个 MP4</option>
              <option value="split">按连续录像拆分</option>
            </select>
          </label>
          <label v-if="gapPolicy === 'split' && hasExportGaps">
            <span>打包</span>
            <select v-model="packageMode">
              <option v-for="mode in packageModes" :key="mode" :value="mode">{{ mode === 'zip' ? 'ZIP（不压缩）' : '多个 MP4' }}</option>
            </select>
          </label>
          <span v-if="exportMode === 'exact'" class="export-cost-note">精确模式 CPU 占用更高</span>
          <el-button type="primary" size="small" :loading="creatingExport" @click="createExportJob">确认导出</el-button>
        </div>
        <div v-else class="export-empty">该范围没有可导出的本地录像，请调整选区。</div>
      </div>
    </section>

    <section v-if="activeExportJob" class="playback-export-job">
      <div class="export-job-head">
        <div>
          <strong>导出任务 #{{ activeExportJob.id }}</strong>
          <span>{{ exportRangeLabel }}</span>
        </div>
        <span class="export-job-status" :class="activeExportJob.status">{{ activeExportJob.status }}</span>
      </div>
      <el-progress
        v-if="activeExportJob.status === 'pending' || activeExportJob.status === 'processing'"
        :percentage="Math.max(0, Math.min(100, Math.round(activeExportJob.progress)))"
        :stroke-width="5"
        :show-text="false"
      />
      <div v-if="activeExportJob.status === 'ready'" class="export-downloads">
        <button v-for="artifact in exportArtifacts" :key="artifact.id" type="button" @click="downloadExportArtifact(artifact)">
          <span>{{ artifact.kind === 'zip' ? '下载 ZIP' : artifact.segment_index ? `下载片段 ${artifact.segment_index}` : '下载 MP4' }}</span>
          <small>{{ formatBytes(artifact.file_size) }}<template v-if="artifact.start_at && artifact.end_at"> · {{ isoClock(artifact.start_at) }}–{{ isoClock(artifact.end_at) }}</template></small>
        </button>
      </div>
      <div v-else-if="activeExportJob.status === 'failed'" class="export-job-error">{{ activeExportJob.error_message || '导出失败' }}</div>
      <div v-else-if="activeExportJob.status === 'expired'" class="export-job-error">导出文件已过期，请重新导出。</div>
    </section>

    <PlaybackTimelineV3
      v-if="selectedCamera"
      :camera-id="selectedCamera"
      :date="selectedDate"
      :recordings="recordings"
      :active-wall-seconds="activeWallSeconds"
      :range-select-enabled="rangeSelectEnabled"
      :selected-range="exportRange"
      @seek="seekWallClock"
      @range-change="handleExportRangeChange"
      @range-commit="handleExportRangeCommit"
    />
  </section>
</template>

<style scoped>
.playback-workspace{min-width:0;max-width:1840px;margin:0 auto;padding:12px 18px 26px;box-sizing:border-box}.playback-main-grid{display:grid;grid-template-columns:160px minmax(0,1fr) 280px;gap:10px;align-items:stretch}.playback-side-slot{position:relative;min-width:0;min-height:0}.playback-sidebar{min-width:0;overflow:hidden;display:flex;flex-direction:column;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.playback-sidebar-section{padding:12px}.playback-sidebar-label{margin-bottom:8px;color:var(--nvr-muted);font-size:9px;font-weight:700;letter-spacing:.06em}.playback-date-picker{width:100%!important;min-width:0}:deep(.playback-date-picker .el-input__wrapper){min-width:0;padding:0 7px}:deep(.playback-date-picker .el-input__inner){min-width:0;font-size:11px}.playback-sidebar-divider{height:1px;flex:none;background:var(--nvr-border)}.playback-camera-head{display:flex;align-items:center;justify-content:space-between;padding:11px 12px 7px}.playback-camera-head strong{font-size:10px}.playback-camera-head span{min-width:20px;padding:2px 6px;border-radius:999px;color:var(--nvr-subtle);background:var(--nvr-input);font-size:8px;text-align:center}.playback-camera-list{min-height:0;overflow:auto;padding:0 7px 9px;scrollbar-gutter:stable}.playback-camera-row{position:relative;width:100%;display:flex;align-items:center;gap:9px;padding:8px 9px;border:1px solid transparent;border-radius:7px;color:var(--nvr-muted);background:transparent;font:inherit;text-align:left;cursor:pointer}.playback-camera-row:hover{background:var(--nvr-hover);color:var(--nvr-text-soft)}.playback-camera-row.active{border-color:color-mix(in srgb,var(--nvr-blue) 44%,var(--nvr-border));color:var(--nvr-text);background:color-mix(in srgb,var(--nvr-blue) 10%,var(--nvr-input))}.playback-camera-row.active::before{content:'';position:absolute;left:-1px;top:7px;bottom:7px;width:2px;border-radius:2px;background:var(--nvr-blue)}.camera-status-dot{width:7px;height:7px;flex:none;border-radius:50%;background:#667386;box-shadow:0 0 0 3px rgba(102,115,134,.09)}.camera-status-dot.online{background:#38b66f;box-shadow:0 0 0 3px rgba(56,182,111,.11)}.camera-status-dot.offline{background:#d15858;box-shadow:0 0 0 3px rgba(209,88,88,.1)}.camera-name{min-width:0;overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.playback-video-panel{min-width:0;align-self:start;padding:10px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.playback-video-meta{min-height:34px;display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:0 2px}.playback-video-title{min-width:0;display:flex;align-items:baseline;gap:8px}.playback-video-title strong{flex:none;font-size:11px}.playback-video-title span{min-width:0;overflow:hidden;color:var(--nvr-subtle);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.playback-video-actions{flex:none;display:flex;align-items:center;gap:8px}.playback-clock{color:var(--nvr-text-soft);font-size:12px;font-variant-numeric:tabular-nums;letter-spacing:.03em}.playback-export-panel,.playback-export-job{margin-top:8px;padding:10px 12px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.export-panel-head,.export-job-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.export-panel-head>div:first-child,.export-job-head>div:first-child{display:flex;align-items:baseline;gap:10px}.export-panel-head strong,.export-job-head strong{font-size:11px}.export-panel-head span,.export-job-head span{color:var(--nvr-muted);font-size:10px;font-variant-numeric:tabular-nums}.export-panel-actions{display:flex;gap:6px}.export-analysis{display:grid;gap:8px;margin-top:9px;padding-top:9px;border-top:1px solid var(--nvr-border)}.export-stats{display:flex;flex-wrap:wrap;gap:12px;color:var(--nvr-muted);font-size:10px}.export-stats strong{color:var(--nvr-text-soft)}.export-gap-list{display:flex;flex-wrap:wrap;gap:5px}.export-gap-list span,.export-gap-list small{padding:3px 6px;border-radius:5px;background:var(--nvr-input);color:var(--nvr-muted);font-size:9px;font-variant-numeric:tabular-nums}.export-options{display:flex;align-items:flex-end;flex-wrap:wrap;gap:8px}.export-options label{display:grid;gap:3px}.export-options label>span{font-size:8px;color:var(--nvr-subtle)}.export-options select{height:27px;padding:0 24px 0 7px;border:1px solid var(--nvr-border);border-radius:6px;background:var(--nvr-input);color:var(--nvr-text-soft);font:inherit;font-size:10px}.export-cost-note,.export-empty,.export-job-error{color:var(--nvr-muted);font-size:10px}.export-cost-note{align-self:center}.export-job-status{padding:3px 7px;border-radius:999px;background:var(--nvr-input);font-size:9px!important;text-transform:uppercase}.export-job-status.ready{color:#38b66f}.export-job-status.failed,.export-job-status.expired{color:#d15858}.playback-export-job :deep(.el-progress){margin-top:9px}.export-downloads{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}.export-downloads button{display:grid;gap:2px;min-width:128px;padding:7px 9px;border:1px solid var(--nvr-border);border-radius:6px;background:var(--nvr-input);color:var(--nvr-text-soft);font:inherit;text-align:left;cursor:pointer}.export-downloads button:hover{border-color:color-mix(in srgb,var(--nvr-blue) 50%,var(--nvr-border))}.export-downloads span{font-size:10px}.export-downloads small{font-size:8px;color:var(--nvr-subtle);font-variant-numeric:tabular-nums}.export-job-error{margin-top:8px}.playback-workspace :deep(.playback-v3){margin-top:10px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.playback-workspace :deep(.playback-event-feed){min-width:0;height:100%}
@media(min-width:1101px){.playback-workspace{display:block;overflow:visible;padding:10px 18px 12px}.playback-main-grid{min-height:0;overflow:hidden}.playback-left-slot>.playback-sidebar{position:absolute;inset:0}.playback-sidebar{min-height:0}.playback-camera-list{flex:1}.playback-workspace :deep(.playback-player .player-box){width:100%;aspect-ratio:16/9}.playback-events-slot :deep(.playback-event-feed){position:absolute;inset:0;min-height:0;display:flex;flex-direction:column}.playback-workspace :deep(.playback-event-feed .event-feed-body){max-height:none;min-height:0;flex:1}.playback-workspace :deep(.playback-v3){margin-top:8px}}
@media(max-width:1100px){.playback-main-grid{grid-template-columns:1fr}.playback-sidebar{max-height:340px}.playback-camera-list{max-height:220px}.playback-workspace :deep(.playback-event-feed){max-height:430px}}
@media(max-width:700px){.playback-workspace{padding:8px}.playback-main-grid{gap:8px}.playback-sidebar-section{padding:10px}.playback-video-meta{align-items:stretch;flex-direction:column;padding-bottom:8px}.playback-video-actions{justify-content:space-between;flex-wrap:wrap}.playback-video-title span{max-width:64%}.export-panel-head,.export-job-head{align-items:flex-start;flex-direction:column}.export-options{align-items:stretch}.export-options label,.export-options select{width:100%}}
</style>