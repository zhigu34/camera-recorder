<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Refresh, Search, WarningFilled } from '@element-plus/icons-vue'
import { useCameraStore } from './stores/cameras'
import type { ExportJob, ExportRangeAnalysis } from './types/exports'
import { buildExportRequest } from './utils/playbackExport'
import { motionPlaybackStartSeconds, wallClockSeconds } from './utils/playbackTimelineV3'

interface EventItem {
  id: number
  camera_id?: number | null
  recording_id?: number | null
  level: string
  category: string
  code: string
  message: string
  metadata_json?: string | null
  created_at: string
}

interface MotionActivityEvent {
  id: number
  camera_id: number
  zone_id?: number | null
  recording_id?: number | null
  started_at: string
  ended_at: string
  peak_score?: number | null
  snapshot_path?: string | null
  metadata_json?: string | null
  created_at?: string | null
}

type SocketState = 'connecting' | 'connected' | 'disconnected'
type CameraFilter = number | 'all' | 'affected'
type EventMode = 'activity' | 'system'
type ActivityCameraFilter = number | 'all'

const PLAYBACK_EVENT_AUTOSTART_KEY = 'camera-recorder:playback-event-autostart'
const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const { cameras } = storeToRefs(cameraStore)
const initialCameraId = positiveRouteId(route.query.camera_id)

const mode = ref<EventMode>(route.query.view === 'system' || route.query.event_id ? 'system' : 'activity')
const activityDate = ref(todayString())
const activityCamera = ref<ActivityCameraFilter>(initialCameraId || 'all')
const activityEvents = ref<MotionActivityEvent[]>([])
const activityLoading = ref(false)
const activityError = ref('')
const activityDetailVisible = ref(false)
const selectedActivity = ref<MotionActivityEvent | null>(null)
const brokenActivitySnapshots = ref<Record<number, boolean>>({})
const zoneNames = ref<Record<number, Record<number, string>>>({})
const exportingActivityId = ref<number | null>(null)

const events = ref<EventItem[]>([])
const loading = ref(false)
const keyword = ref('')
const levelFilter = ref('all')
const categoryFilter = ref('all')
const cameraFilter = ref<CameraFilter>(initialCameraId || 'all')
const systemPage = ref(1)
const systemPageSize = ref(50)
const detailVisible = ref(false)
const selectedEvent = ref<EventItem | null>(null)
const socketState = ref<SocketState>('disconnected')
let eventCursor: number | null = null
let motionCursor: number | null = null
let reconnectTimer: number | null = null
let socket: WebSocket | null = null
let mounted = false

const activityGroups = computed(() => {
  const grouped = new Map<string, MotionActivityEvent[]>()
  for (const event of [...activityEvents.value].sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))) {
    const date = event.started_at?.slice(0, 10) || activityDate.value
    const items = grouped.get(date) || []
    items.push(event)
    grouped.set(date, items)
  }
  return Array.from(grouped.entries()).map(([date, items]) => ({ date, label: activityDayLabel(date), items }))
})
const activityCameraCount = computed(() => new Set(activityEvents.value.map((item) => item.camera_id)).size)
const activityIsLiveDate = computed(() => activityDate.value === todayString())
const activityLiveLabel = computed(() => {
  if (!activityIsLiveDate.value) return '历史活动'
  if (socketState.value === 'connected') return '实时活动已连接'
  if (socketState.value === 'connecting') return '实时活动连接中'
  return '实时活动重连中'
})
const categories = computed(() => Array.from(new Set(events.value.map((item) => item.category).filter(Boolean))).sort())
const levelOptions = computed(() => Array.from(new Set(events.value.map((item) => item.level).filter(Boolean))).sort())
const recent24h = computed(() => {
  const threshold = Date.now() - 24 * 60 * 60 * 1000
  return events.value.filter((item) => {
    const parsed = Date.parse(item.created_at.replace(' ', 'T'))
    return Number.isFinite(parsed) && parsed >= threshold
  }).length
})
const warningCount = computed(() => events.value.filter((item) => ['warning', 'warn'].includes(item.level.toLowerCase())).length)
const errorCount = computed(() => events.value.filter((item) => ['error', 'critical', 'fatal'].includes(item.level.toLowerCase())).length)
const affectedCameras = computed(() => new Set(events.value.map((item) => item.camera_id).filter((id): id is number => typeof id === 'number')).size)
const liveLabel = computed(() => socketState.value === 'connected' ? 'WebSocket 实时事件流' : socketState.value === 'connecting' ? '实时事件流连接中' : '实时事件流重连中')

const filteredEvents = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  return events.value.filter((item) => {
    const level = item.level.toLowerCase()
    if (levelFilter.value === 'warnings' && !['warning', 'warn'].includes(level)) return false
    if (levelFilter.value === 'problems' && !['error', 'critical', 'fatal'].includes(level)) return false
    if (!['all', 'warnings', 'problems'].includes(levelFilter.value) && item.level !== levelFilter.value) return false
    if (categoryFilter.value !== 'all' && item.category !== categoryFilter.value) return false
    if (cameraFilter.value === 'affected' && typeof item.camera_id !== 'number') return false
    if (typeof cameraFilter.value === 'number' && item.camera_id !== cameraFilter.value) return false
    if (!needle) return true
    const camera = cameraName(item.camera_id)
    return [item.message, item.code, item.category, item.level, camera, item.metadata_json || ''].join(' ').toLowerCase().includes(needle)
  })
})
const paginatedEvents = computed(() => {
  const start = (systemPage.value - 1) * systemPageSize.value
  return filteredEvents.value.slice(start, start + systemPageSize.value)
})

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
function positiveRouteId(value: unknown) {
  const raw = Array.isArray(value) ? value[0] : value
  const id = Number(raw || 0)
  return Number.isInteger(id) && id > 0 ? id : null
}
function cameraName(cameraId?: number | null) {
  if (!cameraId) return '-'
  return cameras.value.find((camera) => camera.id === cameraId)?.name || `摄像头 #${cameraId}`
}
function activityDayLabel(date: string) {
  if (date === todayString()) return '今天'
  const yesterday = new Date()
  yesterday.setDate(yesterday.getDate() - 1)
  const yesterdayText = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`
  if (date === yesterdayText) return '昨天'
  return date
}
function activityClock(value: string) {
  const seconds = wallClockSeconds(value)
  if (seconds === null) return '--:--:--'
  const safe = Math.max(0, Math.min(86399, Math.floor(seconds)))
  const hours = Math.floor(safe / 3600)
  const minutes = Math.floor((safe % 3600) / 60)
  const secs = safe % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}
function activityDuration(event: MotionActivityEvent) {
  const start = Date.parse(event.started_at)
  const end = Date.parse(event.ended_at)
  const seconds = Number.isFinite(start) && Number.isFinite(end) ? Math.max(1, Math.round((end - start) / 1000)) : 1
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60)
    const rest = seconds % 60
    return rest ? `${minutes}m ${rest}s` : `${minutes}m`
  }
  return `${seconds}s`
}
function activityScore(event: MotionActivityEvent) {
  if (typeof event.peak_score !== 'number' || !Number.isFinite(event.peak_score)) return null
  return event.peak_score <= 1 ? `${Math.round(event.peak_score * 100)}%` : event.peak_score.toFixed(1)
}
function activityZoneLabel(event: MotionActivityEvent) {
  if (!event.zone_id) return '全画面'
  return zoneNames.value[event.camera_id]?.[event.zone_id] || `区域 #${event.zone_id}`
}
function activitySnapshotUrl(event: MotionActivityEvent) {
  return `/api/motion-events/${event.id}/snapshot`
}
function activitySnapshotAvailable(event: MotionActivityEvent) {
  return Boolean(event.snapshot_path) && !brokenActivitySnapshots.value[event.id]
}
function markActivitySnapshotBroken(eventId: number) {
  brokenActivitySnapshots.value = { ...brokenActivitySnapshots.value, [eventId]: true }
}
function activityDateFor(event: MotionActivityEvent) {
  return event.started_at?.slice(0, 10) || activityDate.value
}
function activityMatchesCurrentView(event: MotionActivityEvent) {
  if (activityDateFor(event) !== activityDate.value) return false
  return activityCamera.value === 'all' || activityCamera.value === event.camera_id
}
function activityPaddedRange(event: MotionActivityEvent, paddingSeconds = 10) {
  const start = wallClockSeconds(event.started_at)
  if (start === null) return null
  const sameDay = event.ended_at?.slice(0, 10) === activityDateFor(event)
  const rawEnd = sameDay ? wallClockSeconds(event.ended_at) : 86400
  const end = rawEnd === null ? start : Math.max(start, rawEnd)
  return {
    start: Math.max(0, start - paddingSeconds),
    end: Math.min(86400, end + paddingSeconds),
  }
}
async function loadActivityZoneName(cameraId: number) {
  if (zoneNames.value[cameraId]) return
  try {
    const response = await axios.get<{ zones?: Array<{ id: number; name: string }> }>(`/api/cameras/${cameraId}/motion-detection`)
    zoneNames.value = {
      ...zoneNames.value,
      [cameraId]: Object.fromEntries((response.data.zones || []).map((zone) => [zone.id, zone.name])),
    }
  } catch {
    // A missing zone name should not block the activity stream.
  }
}
async function loadActivityZoneNames(items: MotionActivityEvent[]) {
  const cameraIds = Array.from(new Set(items.map((item) => item.camera_id)))
  await Promise.allSettled(cameraIds.map((cameraId) => loadActivityZoneName(cameraId)))
}
function mergeActivityEvent(item: MotionActivityEvent) {
  motionCursor = motionCursor === null ? item.id : Math.max(motionCursor, item.id)
  if (mode.value !== 'activity' || !activityMatchesCurrentView(item)) return
  if (activityEvents.value.some((existing) => existing.id === item.id)) return
  activityEvents.value = [item, ...activityEvents.value]
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
    .slice(0, 1000)
  void loadActivityZoneName(item.camera_id)
}
async function loadActivity() {
  activityLoading.value = true
  activityError.value = ''
  brokenActivitySnapshots.value = {}
  activityEvents.value = []
  if (activityIsLiveDate.value) connectEventsSocket()
  else closeSocket()
  try {
    await cameraStore.load()
    const params: Record<string, string | number> = {
      start: `${activityDate.value}T00:00:00`,
      end: `${activityDate.value}T23:59:59.999999`,
      limit: 1000,
    }
    if (typeof activityCamera.value === 'number') params.camera_id = activityCamera.value
    const { data } = await axios.get<MotionActivityEvent[]>('/api/motion-events', { params })
    const combined = new Map<number, MotionActivityEvent>()
    for (const event of data) combined.set(event.id, event)
    for (const event of activityEvents.value) combined.set(event.id, event)
    activityEvents.value = Array.from(combined.values())
      .filter(activityMatchesCurrentView)
      .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
      .slice(0, 1000)
    for (const event of data) motionCursor = motionCursor === null ? event.id : Math.max(motionCursor, event.id)
    await loadActivityZoneNames(activityEvents.value)
  } catch (error) {
    activityEvents.value = []
    activityError.value = axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '活动加载失败'
  } finally {
    activityLoading.value = false
  }
}
function writePlaybackAutostart(eventId: number) {
  try {
    window.sessionStorage.setItem(PLAYBACK_EVENT_AUTOSTART_KEY, String(eventId))
  } catch { /* session storage unavailable */ }
}
function playActivity(event: MotionActivityEvent) {
  const seconds = motionPlaybackStartSeconds(event.started_at)
  if (seconds === null) {
    ElMessage.warning('该活动缺少可用的回放时间')
    return
  }
  writePlaybackAutostart(event.id)
  const query: Record<string, string> = {
    camera_id: String(event.camera_id),
    date: activityDateFor(event),
    event_id: String(event.id),
    wall_seconds: String(seconds),
  }
  if (event.recording_id) query.recording_id = String(event.recording_id)
  void router.push({ path: '/recordings/playback', query })
}
function playActivityWithPadding(event: MotionActivityEvent) {
  const range = activityPaddedRange(event)
  if (!range) {
    ElMessage.warning('该活动缺少可用的回放时间')
    return
  }
  writePlaybackAutostart(event.id)
  const query: Record<string, string> = {
    camera_id: String(event.camera_id),
    date: activityDateFor(event),
    event_id: String(event.id),
    wall_seconds: String(range.start),
    play_until_wall_seconds: String(range.end),
  }
  if (event.recording_id) query.recording_id = String(event.recording_id)
  void router.push({ path: '/recordings/playback', query })
}
async function exportActivityClip(event: MotionActivityEvent) {
  const range = activityPaddedRange(event)
  if (!range) {
    ElMessage.warning('该活动缺少可用的导出时间')
    return
  }
  exportingActivityId.value = event.id
  try {
    const request = buildExportRequest({
      cameraId: event.camera_id,
      date: activityDateFor(event),
      range,
      exportMode: 'fast',
      gapPolicy: 'merge',
      packageMode: 'individual',
    })
    const { data: analysis } = await axios.post<ExportRangeAnalysis>('/api/exports/analyze', {
      camera_id: request.camera_id,
      start_at: request.start_at,
      end_at: request.end_at,
    })
    if (!analysis.exportable) {
      ElMessage.warning('该事件范围没有可导出的本地录像')
      return
    }
    const { data: job } = await axios.post<ExportJob>('/api/exports', request)
    ElMessage.success(`导出任务 #${job.id} 已创建`)
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '事件片段导出失败')
  } finally {
    exportingActivityId.value = null
  }
}
function openActivityDetail(event: MotionActivityEvent) {
  selectedActivity.value = event
  activityDetailVisible.value = true
}
function openActivityCamera(event: MotionActivityEvent) {
  void router.push({ path: '/cameras', query: { camera_id: String(event.camera_id) } })
}
async function setMode(value: EventMode) {
  if (mode.value === value) return
  mode.value = value
  const query = { ...route.query }
  delete query.event_id
  if (value === 'system') query.view = 'system'
  else delete query.view
  void router.replace({ query })
  if (value === 'activity') await loadActivity()
  else {
    await load()
    connectEventsSocket()
  }
}

function levelType(level: string) {
  const value = level.toLowerCase()
  if (['critical', 'fatal', 'error'].includes(value)) return 'danger'
  if (['warning', 'warn'].includes(value)) return 'warning'
  if (['success', 'recovery', 'recovered'].includes(value)) return 'success'
  return 'info'
}
function levelLabel(level: string) {
  const value = level.toLowerCase()
  if (value === 'critical') return '严重'
  if (value === 'fatal') return '致命'
  if (value === 'error') return '错误'
  if (value === 'warning' || value === 'warn') return '警告'
  if (value === 'info') return '信息'
  if (value === 'success') return '正常'
  return level
}
function categoryLabel(category: string) {
  const labels: Record<string, string> = {
    camera: '摄像头', recorder: '录像', recording: '录像', upload: '上传', storage: '存储',
    system: '系统', ffmpeg: 'FFmpeg', playback: '回放', network: '网络', health: '健康',
  }
  return labels[category.toLowerCase()] || category
}
function parsedMetadata(item: EventItem | null): Record<string, unknown> | null {
  if (!item?.metadata_json) return null
  try {
    const value = JSON.parse(item.metadata_json)
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
  } catch { return null }
}
function metadataText(item: EventItem | null) {
  const parsed = parsedMetadata(item)
  return parsed ? JSON.stringify(parsed, null, 2) : item?.metadata_json || ''
}
function openDetail(item: EventItem) {
  selectedEvent.value = item
  detailVisible.value = true
  void router.replace({ query: { ...route.query, view: 'system', event_id: String(item.id) } })
}
function closeDetail() {
  detailVisible.value = false
  selectedEvent.value = null
  const query = { ...route.query }
  delete query.event_id
  void router.replace({ query })
}
function syncDeepLinkedEvent() {
  const eventId = positiveRouteId(route.query.event_id)
  if (!eventId) return
  const item = events.value.find((event) => event.id === eventId)
  if (item) { selectedEvent.value = item; detailVisible.value = true }
}
function clearFilters() { keyword.value = ''; levelFilter.value = 'all'; categoryFilter.value = 'all'; cameraFilter.value = 'all' }
function relatedAction(item: EventItem) {
  const category = item.category.toLowerCase()
  if (item.recording_id) {
    const query: Record<string, string> = { recording_id: String(item.recording_id) }
    if (item.camera_id) query.camera_id = String(item.camera_id)
    return { label: '打开关联录像', action: () => router.push({ path: '/recordings/browser', query }) }
  }
  if (category === 'upload') return { label: '查看上传管理', action: () => router.push('/uploads') }
  if (item.camera_id || category === 'camera') {
    return { label: '打开摄像头', action: () => item.camera_id ? router.push({ path: '/cameras', query: { camera_id: String(item.camera_id) } }) : router.push('/cameras') }
  }
  return { label: '查看系统健康', action: () => router.push('/health-center') }
}
function shouldConnectSocket() {
  return mode.value === 'system' || (mode.value === 'activity' && activityIsLiveDate.value)
}
function wsUrl() {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const params = new URLSearchParams()
  if (eventCursor !== null) params.set('after_id', String(eventCursor))
  if (motionCursor !== null) params.set('after_motion_id', String(motionCursor))
  const suffix = params.toString()
  return `${scheme}//${window.location.host}/ws/events${suffix ? `?${suffix}` : ''}`
}
function mergeEvent(item: EventItem) {
  eventCursor = eventCursor === null ? item.id : Math.max(eventCursor, item.id)
  if (events.value.some((existing) => existing.id === item.id)) return
  events.value = [item, ...events.value].sort((a, b) => b.id - a.id).slice(0, 500)
  syncDeepLinkedEvent()
}
function closeSocket() {
  if (!socket) return
  const current = socket
  socket = null
  current.onopen = null; current.onmessage = null; current.onerror = null; current.onclose = null
  try { current.close() } catch { /* already closed */ }
}
function scheduleReconnect() {
  if (!mounted || !shouldConnectSocket() || reconnectTimer !== null) return
  reconnectTimer = window.setTimeout(() => { reconnectTimer = null; connectEventsSocket() }, 2000)
}
function connectEventsSocket() {
  closeSocket()
  if (!mounted || !shouldConnectSocket()) return
  socketState.value = 'connecting'
  const ws = new WebSocket(wsUrl())
  socket = ws
  ws.onopen = () => { if (socket === ws) socketState.value = 'connected' }
  ws.onmessage = (event: MessageEvent) => {
    if (socket !== ws || typeof event.data !== 'string') return
    try {
      const message = JSON.parse(event.data) as { type?: string; data?: EventItem | MotionActivityEvent }
      if (message.type === 'event.created' && message.data) mergeEvent(message.data as EventItem)
      if (message.type === 'motion.created' && message.data) mergeActivityEvent(message.data as MotionActivityEvent)
    } catch { /* ignore unknown frames */ }
  }
  ws.onerror = () => { if (socket === ws) socketState.value = 'disconnected' }
  ws.onclose = () => { if (socket !== ws) return; socket = null; socketState.value = 'disconnected'; scheduleReconnect() }
}
async function load() {
  loading.value = true
  try {
    const [eventRes] = await Promise.all([
      axios.get<EventItem[]>('/api/events?limit=500'),
      cameraStore.load(),
    ])
    events.value = eventRes.data
    eventCursor = eventRes.data.reduce((maxId, item) => Math.max(maxId, item.id), 0)
    syncDeepLinkedEvent()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '事件加载失败')
  } finally { loading.value = false }
}
async function reload() { await Promise.all([load(), cameraStore.load(true)]); connectEventsSocket() }

watch(() => [activityDate.value, activityCamera.value] as const, () => {
  if (mode.value === 'activity') void loadActivity()
})
watch([keyword, levelFilter, categoryFilter, cameraFilter, systemPageSize], () => { systemPage.value = 1 })
watch(() => filteredEvents.value.length, (length) => {
  const maxPage = Math.max(1, Math.ceil(length / systemPageSize.value))
  if (systemPage.value > maxPage) systemPage.value = maxPage
})
watch(() => route.query.event_id, syncDeepLinkedEvent)
watch(() => route.query.camera_id, (value) => {
  const cameraId = positiveRouteId(value)
  const nextActivity: ActivityCameraFilter = cameraId || 'all'
  const nextSystem: CameraFilter = cameraId || 'all'
  if (activityCamera.value !== nextActivity) activityCamera.value = nextActivity
  if (cameraFilter.value !== nextSystem) cameraFilter.value = nextSystem
})
watch(() => [route.query.view, route.query.event_id] as const, () => {
  const nextMode: EventMode = route.query.view === 'system' || route.query.event_id ? 'system' : 'activity'
  if (nextMode === mode.value) return
  mode.value = nextMode
  if (!mounted) return
  if (nextMode === 'activity') void loadActivity()
  else void load().then(connectEventsSocket)
})
onMounted(() => {
  mounted = true
  void (async () => {
    if (mode.value === 'activity') await loadActivity()
    else { await load(); connectEventsSocket() }
  })()
})
onBeforeUnmount(() => {
  mounted = false
  closeSocket()
  if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
})
</script>

<template>
  <div class="events-page">
    <div class="event-mode-bar">
      <div class="event-mode-copy">
        <strong>{{ mode === 'activity' ? '活动' : '系统事件' }}</strong>
        <span>{{ mode === 'activity' ? '按摄像头查看检测活动并直接进入回放' : '查看录像、存储、网络和系统运行事件' }}</span>
      </div>
      <div class="event-mode-tabs" role="tablist" aria-label="事件视图">
        <button type="button" :class="{ active: mode === 'activity' }" @click="setMode('activity')">活动</button>
        <button type="button" :class="{ active: mode === 'system' }" @click="setMode('system')">系统事件</button>
      </div>
    </div>

    <section v-if="mode === 'activity'" class="activity-center-view" v-loading="activityLoading">
      <div class="activity-toolbar">
        <el-date-picker
          v-model="activityDate"
          type="date"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          class="activity-date"
        />
        <el-select v-model="activityCamera" class="activity-camera" filterable>
          <el-option label="全部摄像头" value="all" />
          <el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" />
        </el-select>
        <span class="activity-summary">{{ activityEvents.length }} 个活动 · {{ activityCameraCount }} 台摄像头</span>
        <span class="activity-live-note"><span class="live-dot" :class="{ offline: activityIsLiveDate && socketState !== 'connected', history: !activityIsLiveDate }"></span>{{ activityLiveLabel }}</span>
        <el-button text :loading="activityLoading" @click="loadActivity">刷新</el-button>
      </div>

      <div v-if="activityError" class="activity-empty activity-error">{{ activityError }}</div>
      <div v-else-if="!activityEvents.length && !activityLoading" class="activity-empty">
        <span class="activity-empty-glyph"></span>
        <strong>这一天没有检测活动</strong>
        <span>可切换日期或摄像头查看其他活动。</span>
      </div>

      <div v-else class="activity-stream">
        <section v-for="group in activityGroups" :key="group.date" class="activity-day-group">
          <header class="activity-day-head">
            <strong>{{ group.label }}</strong>
            <span>{{ group.items.length }} 个活动</span>
          </header>
          <div class="activity-grid">
            <article
              v-for="event in group.items"
              :key="event.id"
              class="activity-card"
              tabindex="0"
              @click="playActivity(event)"
              @keydown.enter="playActivity(event)"
            >
              <div class="activity-thumb">
                <img
                  v-if="activitySnapshotAvailable(event)"
                  :src="activitySnapshotUrl(event)"
                  :alt="`${cameraName(event.camera_id)} 移动检测截图`"
                  loading="lazy"
                  @error="markActivitySnapshotBroken(event.id)"
                />
                <div v-else class="activity-thumb-placeholder"><span class="activity-motion-glyph"></span></div>
                <time>{{ activityClock(event.started_at) }}</time>
                <span class="activity-kind">移动</span>
              </div>
              <div class="activity-card-body">
                <div class="activity-card-title">
                  <strong>{{ cameraName(event.camera_id) }}</strong>
                  <span>{{ activityDuration(event) }}</span>
                </div>
                <div class="activity-card-meta">
                  <span>{{ activityZoneLabel(event) }}</span>
                  <span v-if="activityScore(event)">峰值 {{ activityScore(event) }}</span>
                </div>
                <div class="activity-card-actions">
                  <button type="button" @click.stop="openActivityDetail(event)">详情</button>
                  <span>播放事件 ›</span>
                </div>
              </div>
            </article>
          </div>
        </section>
      </div>

      <el-drawer v-model="activityDetailVisible" title="活动详情" size="420px">
        <template v-if="selectedActivity">
          <div class="activity-detail-image">
            <img
              v-if="activitySnapshotAvailable(selectedActivity)"
              :src="activitySnapshotUrl(selectedActivity)"
              alt="移动检测活动截图"
              @error="markActivitySnapshotBroken(selectedActivity.id)"
            />
            <div v-else class="activity-thumb-placeholder"><span class="activity-motion-glyph"></span></div>
          </div>
          <div class="activity-detail-title">
            <div><span class="activity-dot"></span><strong>移动检测</strong></div>
            <span>{{ activityClock(selectedActivity.started_at) }} · {{ activityDuration(selectedActivity) }}</span>
          </div>
          <dl class="detail-list">
            <div><dt>摄像头</dt><dd>{{ cameraName(selectedActivity.camera_id) }}</dd></div>
            <div><dt>检测区域</dt><dd>{{ activityZoneLabel(selectedActivity) }}</dd></div>
            <div><dt>事件 ID</dt><dd>#{{ selectedActivity.id }}</dd></div>
            <div><dt>关联录像</dt><dd>{{ selectedActivity.recording_id ? `#${selectedActivity.recording_id}` : '-' }}</dd></div>
            <div v-if="activityScore(selectedActivity)"><dt>检测峰值</dt><dd>{{ activityScore(selectedActivity) }}</dd></div>
          </dl>
          <div class="drawer-actions">
            <el-button type="primary" @click="playActivity(selectedActivity)">播放事件</el-button>
            <el-button @click="playActivityWithPadding(selectedActivity)">播放前后 10 秒</el-button>
            <el-button :loading="exportingActivityId === selectedActivity.id" @click="exportActivityClip(selectedActivity)">导出事件片段</el-button>
            <el-button @click="openActivityCamera(selectedActivity)">打开摄像头</el-button>
          </div>
        </template>
      </el-drawer>
    </section>

    <section v-else class="system-event-view" v-loading="loading">
      <div class="actions-row">
        <div class="live-note"><span class="live-dot" :class="{ offline: socketState !== 'connected' }"></span>最近 500 条事件 · {{ liveLabel }}</div>
        <el-button :icon="Refresh" @click="reload">刷新</el-button>
      </div>

      <div class="metrics-grid">
        <button class="metric-card" :class="{ active: levelFilter === 'all' && cameraFilter === 'all' }" @click="levelFilter = 'all'; cameraFilter = 'all'">
          <span>已加载事件</span><strong>{{ events.length }}</strong><small>最近 24h {{ recent24h }}</small>
        </button>
        <button class="metric-card warning" :class="{ active: levelFilter === 'warnings' }" @click="levelFilter = 'warnings'">
          <span>警告</span><strong>{{ warningCount }}</strong><small>warning / warn</small>
        </button>
        <button class="metric-card danger" :class="{ active: levelFilter === 'problems' }" @click="levelFilter = 'problems'">
          <span>错误 / 严重</span><strong>{{ errorCount }}</strong><small>error / critical / fatal</small>
        </button>
        <button class="metric-card" :class="{ active: cameraFilter === 'affected' }" @click="cameraFilter = 'affected'">
          <span>涉及摄像头</span><strong>{{ affectedCameras }}</strong><small>仅显示设备相关事件</small>
        </button>
      </div>

      <div class="filter-bar">
        <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索消息、事件码、分类、摄像头或元数据" class="search-input" />
        <el-select v-model="levelFilter" class="filter-select" placeholder="级别">
          <el-option label="全部级别" value="all" /><el-option label="警告类" value="warnings" /><el-option label="错误 / 严重" value="problems" />
          <el-option v-for="level in levelOptions" :key="level" :label="levelLabel(level)" :value="level" />
        </el-select>
        <el-select v-model="categoryFilter" class="filter-select" placeholder="分类">
          <el-option label="全部分类" value="all" /><el-option v-for="category in categories" :key="category" :label="categoryLabel(category)" :value="category" />
        </el-select>
        <el-select v-model="cameraFilter" class="camera-select" filterable placeholder="摄像头">
          <el-option label="全部摄像头" value="all" /><el-option label="所有设备相关事件" value="affected" /><el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" />
        </el-select>
        <el-button text @click="clearFilters">清除筛选</el-button><span class="result-count">{{ filteredEvents.length }} 条</span>
      </div>

      <div class="table-panel">
        <el-table :data="paginatedEvents" height="calc(100vh - 408px)" empty-text="暂无匹配事件" @row-click="openDetail">
          <el-table-column prop="created_at" label="时间" width="170" />
          <el-table-column label="级别" width="88"><template #default="{ row }"><el-tag size="small" :type="levelType(row.level)">{{ levelLabel(row.level) }}</el-tag></template></el-table-column>
          <el-table-column label="分类" width="108"><template #default="{ row }">{{ categoryLabel(row.category) }}</template></el-table-column>
          <el-table-column prop="code" label="事件码" min-width="150" show-overflow-tooltip />
          <el-table-column label="摄像头" min-width="145" show-overflow-tooltip><template #default="{ row }">{{ cameraName(row.camera_id) }}</template></el-table-column>
          <el-table-column prop="message" label="消息" min-width="320" show-overflow-tooltip />
          <el-table-column label="关联" width="110"><template #default="{ row }"><span v-if="row.recording_id" class="relation">录像 #{{ row.recording_id }}</span><span v-else-if="row.camera_id" class="relation">摄像头 #{{ row.camera_id }}</span><span v-else class="muted">系统</span></template></el-table-column>
          <el-table-column label="" width="52" fixed="right"><template #default><span class="open-arrow">›</span></template></el-table-column>
        </el-table>
        <div class="system-pagination">
          <span>共 {{ filteredEvents.length }} 条</span>
          <el-pagination
            v-model:current-page="systemPage"
            v-model:page-size="systemPageSize"
            :page-sizes="[20, 50, 100]"
            :total="filteredEvents.length"
            layout="prev, pager, next, sizes"
            small
            background
          />
        </div>
      </div>

      <el-drawer v-model="detailVisible" title="事件详情" size="460px" @closed="closeDetail">
        <template v-if="selectedEvent">
          <div class="detail-hero" :class="levelType(selectedEvent.level)"><WarningFilled class="detail-icon" /><div><el-tag size="small" :type="levelType(selectedEvent.level)">{{ levelLabel(selectedEvent.level) }}</el-tag><strong>{{ selectedEvent.message }}</strong><span>{{ selectedEvent.created_at }}</span></div></div>
          <dl class="detail-list">
            <div><dt>事件 ID</dt><dd>#{{ selectedEvent.id }}</dd></div><div><dt>分类</dt><dd>{{ categoryLabel(selectedEvent.category) }}</dd></div><div><dt>事件码</dt><dd><code>{{ selectedEvent.code }}</code></dd></div><div><dt>摄像头</dt><dd>{{ cameraName(selectedEvent.camera_id) }}</dd></div><div><dt>录像</dt><dd>{{ selectedEvent.recording_id ? `#${selectedEvent.recording_id}` : '-' }}</dd></div>
          </dl>
          <div v-if="selectedEvent.metadata_json" class="metadata-block"><div class="section-label">元数据</div><pre>{{ metadataText(selectedEvent) }}</pre></div>
          <div class="drawer-actions"><el-button type="primary" @click="relatedAction(selectedEvent).action()">{{ relatedAction(selectedEvent).label }}</el-button><el-button @click="closeDetail">关闭</el-button></div>
        </template>
      </el-drawer>
    </section>
  </div>
</template>

<style scoped>
.events-page{padding:14px 18px 28px;color:var(--nvr-text)}
.event-mode-bar{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:12px}.event-mode-copy{display:grid;gap:3px}.event-mode-copy strong{font-size:15px;font-weight:650}.event-mode-copy span{color:var(--nvr-subtle);font-size:10px}.event-mode-tabs{display:flex;padding:3px;border:1px solid var(--nvr-border);border-radius:8px;background:var(--nvr-input)}.event-mode-tabs button{height:28px;padding:0 12px;border:0;border-radius:6px;color:var(--nvr-muted);background:transparent;font:inherit;font-size:10px;cursor:pointer}.event-mode-tabs button.active{color:var(--nvr-text);background:var(--nvr-surface);box-shadow:0 1px 2px rgba(0,0,0,.12)}
.activity-center-view{min-height:360px}.activity-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:12px;padding:8px 10px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.activity-date{width:145px!important}.activity-camera{width:190px}.activity-summary{margin-left:auto;color:var(--nvr-muted);font-size:10px;font-variant-numeric:tabular-nums}.activity-live-note{display:flex;align-items:center;gap:6px;color:var(--nvr-muted);font-size:9px;white-space:nowrap}.activity-stream{display:grid;gap:18px}.activity-day-group{display:grid;gap:8px}.activity-day-head{display:flex;align-items:baseline;justify-content:space-between;padding:0 2px}.activity-day-head strong{font-size:11px}.activity-day-head span{color:var(--nvr-subtle);font-size:9px}.activity-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:9px}.activity-card{min-width:0;overflow:hidden;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface);cursor:pointer;transition:transform .12s ease,border-color .12s ease,background .12s ease}.activity-card:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--nvr-blue) 42%,var(--nvr-border));background:var(--nvr-surface-2)}.activity-card:focus-visible{outline:2px solid color-mix(in srgb,var(--nvr-blue) 62%,transparent);outline-offset:2px}.activity-thumb{position:relative;aspect-ratio:16/9;overflow:hidden;background:#05090d}.activity-thumb img,.activity-detail-image img{display:block;width:100%;height:100%;object-fit:cover}.activity-thumb::after{content:'';position:absolute;inset:48% 0 0;background:linear-gradient(180deg,transparent,rgba(0,0,0,.7))}.activity-thumb time{position:absolute;z-index:1;left:8px;bottom:7px;color:#fff;font-size:9px;font-variant-numeric:tabular-nums}.activity-kind{position:absolute;z-index:1;top:7px;left:7px;padding:3px 6px;border-radius:999px;color:#fff;background:rgba(13,20,30,.62);backdrop-filter:blur(5px);font-size:8px}.activity-thumb-placeholder{width:100%;height:100%;display:grid;place-items:center;background:radial-gradient(circle at 50% 45%,color-mix(in srgb,var(--nvr-blue) 15%,transparent),transparent 42%),#070c12}.activity-motion-glyph{width:22px;height:22px;border:1.5px solid color-mix(in srgb,var(--nvr-blue) 72%,#fff);border-radius:50%;box-shadow:0 0 0 6px color-mix(in srgb,var(--nvr-blue) 9%,transparent)}.activity-card-body{display:grid;gap:7px;padding:9px 10px 8px}.activity-card-title{display:flex;align-items:center;justify-content:space-between;gap:8px}.activity-card-title strong{min-width:0;overflow:hidden;font-size:10.5px;text-overflow:ellipsis;white-space:nowrap}.activity-card-title span{flex:none;color:var(--nvr-subtle);font-size:8.5px}.activity-card-meta{display:flex;align-items:center;gap:8px;color:var(--nvr-muted);font-size:8.5px}.activity-card-meta span+span::before{content:'·';margin-right:8px;color:var(--nvr-subtle)}.activity-card-actions{display:flex;align-items:center;justify-content:space-between;padding-top:4px;border-top:1px solid color-mix(in srgb,var(--nvr-border) 58%,transparent)}.activity-card-actions button{padding:0;border:0;color:var(--nvr-muted);background:transparent;font:inherit;font-size:8.5px;cursor:pointer}.activity-card-actions button:hover{color:var(--nvr-text)}.activity-card-actions>span{color:var(--nvr-blue);font-size:8.5px}.activity-empty{min-height:320px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;border:1px dashed var(--nvr-border);border-radius:10px;color:var(--nvr-subtle);font-size:10px;text-align:center}.activity-empty strong{color:var(--nvr-muted);font-size:11px}.activity-empty-glyph{width:24px;height:24px;border:1px solid var(--nvr-border);border-radius:50%;box-shadow:0 0 0 7px var(--nvr-input)}.activity-error{color:var(--nvr-red)}.activity-detail-image{aspect-ratio:16/9;overflow:hidden;border-radius:9px;background:#060b10}.activity-detail-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:12px}.activity-detail-title>div{display:flex;align-items:center;gap:7px}.activity-detail-title strong{font-size:13px}.activity-detail-title>span{color:var(--nvr-muted);font-size:10px;font-variant-numeric:tabular-nums}.activity-dot{width:7px;height:7px;border-radius:50%;background:var(--nvr-blue);box-shadow:0 0 0 4px color-mix(in srgb,var(--nvr-blue) 10%,transparent)}
.actions-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.live-note{display:flex;align-items:center;gap:8px;color:var(--nvr-muted);font-size:12px}.live-dot{width:7px;height:7px;border-radius:50%;background:var(--nvr-green);box-shadow:0 0 0 4px color-mix(in srgb,var(--nvr-green) 8%,transparent)}.live-dot.offline{background:var(--nvr-yellow);box-shadow:0 0 0 4px color-mix(in srgb,var(--nvr-yellow) 8%,transparent)}.live-dot.history{background:var(--nvr-subtle);box-shadow:none}
.metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px}.metric-card{appearance:none;display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:14px 16px;color:var(--nvr-text);background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px;cursor:pointer;text-align:left}.metric-card:hover,.metric-card.active{border-color:color-mix(in srgb,var(--nvr-blue) 45%,var(--nvr-border));background:var(--nvr-surface-2)}.metric-card span{font-size:11px;color:var(--nvr-muted)}.metric-card strong{font-size:24px;font-weight:650;line-height:1}.metric-card small{font-size:10px;color:var(--nvr-subtle)}.metric-card.warning strong{color:var(--nvr-yellow)}.metric-card.danger strong{color:var(--nvr-red)}
.filter-bar{display:flex;align-items:center;gap:8px;margin-bottom:10px;padding:10px;background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px}.search-input{min-width:280px;flex:1}.filter-select{width:126px}.camera-select{width:170px}.result-count{margin-left:auto;color:var(--nvr-muted);font-size:11px;white-space:nowrap}
.table-panel{overflow:hidden;background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px}.relation{color:color-mix(in srgb,var(--nvr-blue) 58%,var(--nvr-text));font-size:11px}.muted{color:var(--nvr-muted)}.open-arrow{color:var(--nvr-subtle);font-size:20px}.table-panel :deep(.el-table__row){cursor:pointer}.system-pagination{min-height:42px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:7px 10px;border-top:1px solid var(--nvr-border)}.system-pagination>span{color:var(--nvr-muted);font-size:9px;white-space:nowrap}
.detail-hero{display:flex;gap:12px;padding:14px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface-2)}.detail-icon{flex:0 0 22px;width:22px;margin-top:2px;color:var(--nvr-muted)}.detail-hero.warning .detail-icon{color:var(--nvr-yellow)}.detail-hero.danger .detail-icon{color:var(--nvr-red)}.detail-hero>div{display:flex;min-width:0;flex-direction:column;align-items:flex-start;gap:7px}.detail-hero strong{font-size:14px;line-height:1.55}.detail-hero span{color:var(--nvr-muted);font-size:11px}.detail-list{margin:16px 0}.detail-list>div{display:grid;grid-template-columns:90px minmax(0,1fr);padding:9px 0;border-bottom:1px solid var(--nvr-border)}.detail-list dt{color:var(--nvr-muted);font-size:11px}.detail-list dd{margin:0;font-size:12px;word-break:break-all}.detail-list code{font-size:11px;color:color-mix(in srgb,var(--nvr-blue) 62%,var(--nvr-text))}.section-label{margin-bottom:7px;color:var(--nvr-muted);font-size:10px;font-weight:700;letter-spacing:.08em}.metadata-block pre{max-height:280px;overflow:auto;margin:0;padding:12px;color:var(--nvr-text-soft);background:var(--nvr-surface-2);border:1px solid var(--nvr-border);border-radius:8px;font-size:11px;line-height:1.55;white-space:pre-wrap;word-break:break-all}.drawer-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
@media(max-width:1000px){.event-mode-bar{align-items:stretch;flex-direction:column}.event-mode-tabs{align-self:flex-start}.activity-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.filter-bar,.activity-toolbar{flex-wrap:wrap}.search-input{flex-basis:100%}.activity-summary,.result-count{margin-left:0}}
@media(max-width:640px){.events-page{padding:10px}.activity-grid{grid-template-columns:1fr}.activity-toolbar{align-items:stretch}.activity-date,.activity-camera{width:100%!important}.metrics-grid{grid-template-columns:1fr 1fr}.filter-select,.camera-select{width:calc(50% - 4px)}.system-pagination{align-items:flex-start;flex-direction:column}}
</style>
