<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import axios from 'axios'

import { type CameraHealth, useRuntimeStore } from './stores/runtime'
import { wallClockSeconds } from './utils/playbackTimelineV3'

interface MotionActivityEvent {
  id: number
  camera_id: number
  zone_id?: number | null
  recording_id?: number | null
  started_at: string
  ended_at: string
  peak_score?: number | null
  snapshot_path?: string | null
  created_at?: string | null
}

interface ActivitySocketMessage {
  type?: string
  data?: MotionActivityEvent
}

type ActivitySocketState = 'idle' | 'connecting' | 'connected' | 'disconnected'
type PreviewStream = 'auto' | 'sub' | 'main'
type LayoutCount = 1 | 4 | 9
interface SavedWallSlot { cameraId: number | null; stream: PreviewStream }
interface SavedWall { layout?: LayoutCount; slots?: SavedWallSlot[] }

const PLAYBACK_EVENT_AUTOSTART_KEY = 'camera-recorder:playback-event-autostart'
const LIVE_WALL_STORAGE_KEY = 'nvr-video-wall-v1'
const ACTIVITY_FALLBACK_REFRESH_MS = 60_000
const ACTIVITY_RECONNECT_MS = 5_000
const ACTIVITY_FRESH_MS = 1_800
const ACTIVITY_MAX_ITEMS = 100
const HOME_SYSTEM_EVENT_CURSOR = Number.MAX_SAFE_INTEGER

const router = useRouter()
const runtime = useRuntimeStore()
const {
  healthSnapshot: summary,
  systemStatus: system,
  socketState,
  loading: runtimeLoading,
} = storeToRefs(runtime)

const activities = ref<MotionActivityEvent[]>([])
const activityLoading = ref(false)
const activityError = ref('')
const activitySocketState = ref<ActivitySocketState>('idle')
const brokenSnapshots = ref<Record<number, boolean>>({})
const freshActivityIds = ref<Set<number>>(new Set())
let activitySocket: WebSocket | null = null
let activityReconnectTimer: number | null = null
let activityFallbackTimer: number | null = null
let activitySocketGeneration = 0
let activityMotionCursor = 0
const freshActivityTimers = new Map<number, number>()

const loading = computed(() => runtimeLoading.value && !summary.value)
const recentActivities = computed(() => activities.value.slice(0, 8))
const pendingUploads = computed(() => {
  const rows = summary.value?.uploads || {}
  return (rows.pending || 0) + (rows.uploading || 0) + (rows.retry_wait || 0)
})
const uploadFailures = computed(() => summary.value?.uploads?.failed || 0)
const overallHealthy = computed(() => Boolean(
  summary.value &&
  summary.value.cameras.abnormal === 0 &&
  summary.value.storage.state !== 'critical' &&
  uploadFailures.value === 0 &&
  system.value?.ffmpeg?.setts_available !== false,
))
const healthClass = computed(() => overallHealthy.value ? 'healthy' : 'attention')
const healthLabel = computed(() => overallHealthy.value ? '系统运行正常' : '有项目需要关注')
const statusFeedLabel = computed(() => socketState.value === 'connected' ? '状态实时更新' : '状态轮询更新')
const activityFeedLabel = computed(() => {
  if (activitySocketState.value === 'connected') return '活动实时更新'
  if (activitySocketState.value === 'connecting') return '正在连接活动'
  return '断线补偿中'
})
const activityFeedClass = computed(() => activitySocketState.value === 'connected' ? 'live' : 'fallback')
const attentionCount = computed(() => (summary.value?.cameras.abnormal || 0) + uploadFailures.value)
const latestActivityByCamera = computed(() => {
  const result = new Map<number, MotionActivityEvent>()
  for (const event of activities.value) {
    if (!result.has(event.camera_id)) result.set(event.camera_id, event)
  }
  return result
})

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
function bytes(value?: number) {
  const amount = value || 0
  if (amount >= 1024 ** 4) return `${(amount / 1024 ** 4).toFixed(2)} TB`
  if (amount >= 1024 ** 3) return `${(amount / 1024 ** 3).toFixed(1)} GB`
  if (amount >= 1024 ** 2) return `${(amount / 1024 ** 2).toFixed(0)} MB`
  return `${Math.round(amount / 1024)} KB`
}
function uptime(value?: number) {
  const seconds = value || 0
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  if (days) return `${days}天 ${hours}小时`
  if (hours) return `${hours}小时`
  return `${Math.max(0, Math.floor(seconds / 60))}分钟`
}
function cameraName(cameraId: number) {
  return summary.value?.camera_health.find((camera) => camera.camera_id === cameraId)?.name || `摄像头 #${cameraId}`
}
function connectivityLabel(state: CameraHealth['connectivity_status']) {
  if (state === 'online') return '在线'
  if (state === 'offline') return '离线'
  return '状态未知'
}
function connectivitySourceLabel(camera: CameraHealth) {
  if (!camera.enabled) return '已停用'
  if (camera.connectivity_source === 'recorder') return '录像信号'
  if (camera.connectivity_source === 'rtsp') return 'RTSP 检测'
  return '历史状态'
}
function connectivityClass(camera: CameraHealth) {
  if (!camera.enabled) return 'muted'
  if (camera.connectivity_status === 'online') return 'success'
  if (camera.connectivity_status === 'offline') return 'danger'
  return 'warning'
}
function recorderLabel(state: string) {
  if (state === 'RECORDING') return '录像中'
  if (state === 'RECONNECTING') return '重连中'
  if (state === 'STARTING') return '启动中'
  if (state === 'STOPPING') return '停止中'
  return '未录像'
}
function recorderClass(state: string) {
  if (state === 'RECORDING') return 'success'
  if (state === 'RECONNECTING' || state === 'STARTING' || state === 'STOPPING') return 'warning'
  return 'muted'
}
function activityClock(value: string) {
  const seconds = wallClockSeconds(value)
  if (seconds === null) return '--:--'
  const safe = Math.max(0, Math.min(86399, Math.floor(seconds)))
  return `${String(Math.floor(safe / 3600)).padStart(2, '0')}:${String(Math.floor((safe % 3600) / 60)).padStart(2, '0')}`
}
function activityRelative(value: string) {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return activityClock(value)
  const minutes = Math.floor(Math.max(0, Date.now() - timestamp) / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return value.slice(0, 10)
}
function activityDuration(event: MotionActivityEvent) {
  const start = Date.parse(event.started_at)
  const end = Date.parse(event.ended_at)
  const seconds = Number.isFinite(start) && Number.isFinite(end) ? Math.max(1, Math.round((end - start) / 1000)) : 1
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`
}
function snapshotUrl(event: MotionActivityEvent) {
  return `/api/motion-events/${event.id}/snapshot`
}
function snapshotAvailable(event: MotionActivityEvent) {
  return Boolean(event.snapshot_path) && !brokenSnapshots.value[event.id]
}
function markSnapshotBroken(eventId: number) {
  brokenSnapshots.value = { ...brokenSnapshots.value, [eventId]: true }
}
function latestActivityLabel(cameraId: number) {
  const event = latestActivityByCamera.value.get(cameraId)
  return event ? activityRelative(event.started_at) : '今天暂无活动'
}
function writePlaybackAutostart(eventId: number) {
  try {
    window.sessionStorage.setItem(PLAYBACK_EVENT_AUTOSTART_KEY, String(eventId))
  } catch {
    // Playback remains reachable even if session storage is disabled.
  }
}
function playActivity(event: MotionActivityEvent) {
  const seconds = wallClockSeconds(event.started_at)
  if (seconds === null) return
  writePlaybackAutostart(event.id)
  const query: Record<string, string> = {
    camera_id: String(event.camera_id),
    date: event.started_at.slice(0, 10) || todayString(),
    event_id: String(event.id),
    wall_seconds: String(seconds),
  }
  if (event.recording_id) query.recording_id = String(event.recording_id)
  void router.push({ path: '/recordings/playback', query })
}
function safePreviewStream(value: unknown): PreviewStream {
  return value === 'main' || value === 'sub' ? value : 'auto'
}
function readSavedWall(): SavedWall {
  try {
    const raw = window.localStorage.getItem(LIVE_WALL_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as SavedWall
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}
function primeLiveCamera(cameraId: number) {
  try {
    const saved = readSavedWall()
    const layout: LayoutCount = saved.layout === 1 || saved.layout === 4 || saved.layout === 9 ? saved.layout : 4
    const slots: SavedWallSlot[] = Array.from({ length: 9 }, (_, index) => {
      const source = Array.isArray(saved.slots) ? saved.slots[index] : undefined
      return {
        cameraId: typeof source?.cameraId === 'number' ? source.cameraId : null,
        stream: safePreviewStream(source?.stream),
      }
    })
    let target = slots.slice(0, layout).findIndex((slot) => slot.cameraId === cameraId)
    if (target < 0) {
      target = slots.slice(0, layout).findIndex((slot) => slot.cameraId === null)
      if (target < 0) target = 0
      slots.forEach((slot, index) => {
        if (index !== target && slot.cameraId === cameraId) slot.cameraId = null
      })
      slots[target] = { cameraId, stream: safePreviewStream(slots[target]?.stream) }
    }
    window.localStorage.setItem(LIVE_WALL_STORAGE_KEY, JSON.stringify({ layout, slots }))
  } catch {
    // Live falls back to its own saved/default wall.
  }
  void router.push({ path: '/preview' })
}
function openCameraSettings(cameraId: number) {
  void router.push({ path: '/cameras', query: { camera_id: String(cameraId) } })
}
function openAllActivity() { void router.push('/events') }
function openHealth() { void router.push('/health-center') }

function updateActivityCursor(events: MotionActivityEvent[]) {
  for (const event of events) activityMotionCursor = Math.max(activityMotionCursor, event.id)
}

async function seedActivityCursor() {
  if (activityMotionCursor > 0) return
  try {
    const { data } = await axios.get<MotionActivityEvent[]>('/api/motion-events', { params: { limit: 1 } })
    updateActivityCursor(data)
  } catch {
    // The socket can still recover the cursor later; do not turn cursor seeding into a visible error.
  }
}

async function loadActivities() {
  activityLoading.value = true
  activityError.value = ''
  const date = todayString()
  try {
    const { data } = await axios.get<MotionActivityEvent[]>('/api/motion-events', {
      params: {
        start: `${date}T00:00:00`,
        end: `${date}T23:59:59.999999`,
        limit: ACTIVITY_MAX_ITEMS,
      },
    })
    updateActivityCursor(data)
    activities.value = [...data]
      .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
      .slice(0, ACTIVITY_MAX_ITEMS)
    if (!data.length) await seedActivityCursor()
  } catch (error) {
    activityError.value = axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '活动加载失败'
    await seedActivityCursor()
  } finally {
    activityLoading.value = false
  }
}

function markActivityFresh(eventId: number) {
  const next = new Set(freshActivityIds.value)
  next.add(eventId)
  freshActivityIds.value = next
  const oldTimer = freshActivityTimers.get(eventId)
  if (oldTimer !== undefined) window.clearTimeout(oldTimer)
  freshActivityTimers.set(eventId, window.setTimeout(() => {
    const current = new Set(freshActivityIds.value)
    current.delete(eventId)
    freshActivityIds.value = current
    freshActivityTimers.delete(eventId)
  }, ACTIVITY_FRESH_MS))
}

function mergeRealtimeActivity(event: MotionActivityEvent) {
  activityMotionCursor = Math.max(activityMotionCursor, event.id)
  if (event.started_at.slice(0, 10) !== todayString()) return
  const existed = activities.value.some((item) => item.id === event.id)
  activities.value = [event, ...activities.value.filter((item) => item.id !== event.id)]
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
    .slice(0, ACTIVITY_MAX_ITEMS)
  if (!existed) markActivityFresh(event.id)
}

function activityEventsWsUrl() {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const params = new URLSearchParams({
    after_id: String(HOME_SYSTEM_EVENT_CURSOR),
    after_motion_id: String(activityMotionCursor),
  })
  return `${scheme}//${window.location.host}/ws/events?${params.toString()}`
}

function clearActivityReconnect() {
  if (activityReconnectTimer !== null) window.clearTimeout(activityReconnectTimer)
  activityReconnectTimer = null
}
function stopActivityFallback() {
  if (activityFallbackTimer !== null) window.clearInterval(activityFallbackTimer)
  activityFallbackTimer = null
}
function startActivityFallback() {
  if (activityFallbackTimer !== null || document.hidden) return
  activityFallbackTimer = window.setInterval(() => {
    if (document.hidden || activitySocketState.value === 'connected') return
    void loadActivities()
  }, ACTIVITY_FALLBACK_REFRESH_MS)
}
function closeActivitySocket(nextState: ActivitySocketState = 'idle') {
  activitySocketGeneration += 1
  const current = activitySocket
  activitySocket = null
  if (current) {
    current.onopen = null
    current.onmessage = null
    current.onerror = null
    current.onclose = null
    try { current.close() } catch { /* already closed */ }
  }
  activitySocketState.value = nextState
}
function scheduleActivityReconnect() {
  if (document.hidden || activityReconnectTimer !== null) return
  activityReconnectTimer = window.setTimeout(() => {
    activityReconnectTimer = null
    connectActivitySocket()
  }, ACTIVITY_RECONNECT_MS)
}
function connectActivitySocket() {
  if (document.hidden) return
  clearActivityReconnect()
  closeActivitySocket('connecting')
  const generation = activitySocketGeneration
  const ws = new WebSocket(activityEventsWsUrl())
  activitySocket = ws

  ws.onopen = () => {
    if (generation !== activitySocketGeneration || activitySocket !== ws) return
    activitySocketState.value = 'connected'
    stopActivityFallback()
  }
  ws.onmessage = (event: MessageEvent) => {
    if (generation !== activitySocketGeneration || activitySocket !== ws || typeof event.data !== 'string') return
    try {
      const message = JSON.parse(event.data) as ActivitySocketMessage
      if (message.type === 'motion.created' && message.data) mergeRealtimeActivity(message.data)
    } catch {
      // Ignore unknown event frames; the REST fallback can reconcile state if needed.
    }
  }
  ws.onerror = () => {
    if (generation !== activitySocketGeneration || activitySocket !== ws) return
    activitySocketState.value = 'disconnected'
    startActivityFallback()
  }
  ws.onclose = () => {
    if (generation !== activitySocketGeneration || activitySocket !== ws) return
    activitySocket = null
    activitySocketState.value = 'disconnected'
    startActivityFallback()
    scheduleActivityReconnect()
  }
}

async function syncActivityFeed() {
  await loadActivities()
  if (!document.hidden) connectActivitySocket()
}
function handleVisibilityChange() {
  if (document.hidden) {
    clearActivityReconnect()
    stopActivityFallback()
    closeActivitySocket('idle')
    return
  }
  void syncActivityFeed()
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  void syncActivityFeed()
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  clearActivityReconnect()
  stopActivityFallback()
  closeActivitySocket('idle')
  for (const timer of freshActivityTimers.values()) window.clearTimeout(timer)
  freshActivityTimers.clear()
})
</script>

<template>
  <div class="protect-home" v-loading="loading">
    <header class="home-header">
      <div class="home-heading">
        <span class="eyebrow">HOME</span>
        <h1>监控概览</h1>
        <p>先看值得关注的活动与设备状态，需要时再进入实时监控或回放。</p>
      </div>
      <div class="health-pill" :class="healthClass" role="button" tabindex="0" @click="openHealth" @keydown.enter="openHealth">
        <span class="health-dot"></span>
        <div>
          <strong>{{ healthLabel }}</strong>
          <small>{{ statusFeedLabel }} · 已运行 {{ uptime(summary?.uptime_seconds) }}</small>
        </div>
      </div>
    </header>

    <section class="status-strip" aria-label="系统状态摘要">
      <div class="status-cell"><span>摄像头</span><strong>{{ summary?.cameras.online ?? '-' }}<small> / {{ summary?.cameras.enabled ?? '-' }} 在线</small></strong></div>
      <div class="status-cell"><span>录像</span><strong>{{ summary?.cameras.recording ?? '-' }}<small> 路运行中</small></strong></div>
      <div class="status-cell"><span>存储</span><strong>{{ summary?.storage.used_percent ?? '-' }}<small>% 已使用</small></strong></div>
      <div class="status-cell attention-cell"><span>需要关注</span><strong>{{ attentionCount }}<small> 项</small></strong></div>
    </section>

    <section class="home-primary-grid">
      <article class="surface activity-surface">
        <header class="section-head">
          <div>
            <span class="section-kicker">ACTIVITY</span>
            <h2>最近活动</h2>
            <p>今天的移动检测快照；点击活动直接进入对应回放。</p>
          </div>
          <div class="activity-head-actions">
            <span class="activity-feed-state" :class="activityFeedClass"><i></i>{{ activityFeedLabel }}</span>
            <button type="button" class="quiet-link" @click="openAllActivity">查看全部 ›</button>
          </div>
        </header>

        <div v-if="activityError && !activities.length" class="activity-empty">
          <strong>暂时无法加载活动</strong><span>{{ activityError }}</span><button type="button" @click="loadActivities">重试</button>
        </div>
        <div v-else-if="!recentActivities.length && !activityLoading" class="activity-empty">
          <span class="empty-motion-mark"></span><strong>今天还没有检测活动</strong><span>新的移动事件会实时显示在这里，不会自动打开任何视频流。</span>
        </div>
        <div v-else class="activity-grid">
          <button v-for="event in recentActivities" :key="event.id" type="button" :class="freshActivityIds.has(event.id) ? 'activity-card fresh' : 'activity-card'" @click="playActivity(event)">
            <span class="activity-thumb">
              <img v-if="snapshotAvailable(event)" :src="snapshotUrl(event)" :alt="`${cameraName(event.camera_id)} 活动截图`" loading="lazy" @error="markSnapshotBroken(event.id)" />
              <span v-else class="activity-placeholder"><i></i></span>
              <time>{{ activityClock(event.started_at) }}</time><span class="activity-badge">移动</span><span class="play-mark">▶</span>
            </span>
            <span class="activity-copy">
              <span class="activity-title"><strong>{{ cameraName(event.camera_id) }}</strong><small>{{ activityDuration(event) }}</small></span>
              <span class="activity-meta"><span>{{ activityRelative(event.started_at) }}</span><i>播放事件 ›</i></span>
            </span>
          </button>
        </div>
      </article>

      <aside class="surface system-surface">
        <header class="section-head compact"><div><span class="section-kicker">SYSTEM</span><h2>系统状态</h2></div><button type="button" class="quiet-link" @click="openHealth">详情 ›</button></header>
        <div class="system-body">
          <div class="storage-line">
            <div class="storage-title"><span>录像存储</span><strong>{{ summary?.storage.used_percent ?? '-' }}%</strong></div>
            <div class="storage-track"><i :style="{ width: `${Math.min(100, summary?.storage.used_percent || 0)}%` }"></i></div>
            <div class="storage-copy"><span>{{ bytes(summary?.storage.used_bytes) }} 已使用</span><span>{{ bytes(summary?.storage.free_bytes) }} 可用</span></div>
          </div>
          <div class="system-list">
            <div><span>24 小时录像</span><strong>{{ summary?.recordings_24h.segments ?? '-' }} 片段</strong><small>{{ summary?.recordings_24h.unhealthy_segments ?? 0 }} 异常</small></div>
            <div><span>上传队列</span><strong>{{ pendingUploads }} 待处理</strong><small>{{ uploadFailures }} 失败</small></div>
            <div><span>FFmpeg / setts</span><strong>{{ system?.ffmpeg?.setts_available === false ? '异常' : system?.ffmpeg ? '正常' : '检测中' }}</strong><small>{{ system?.ffmpeg?.ffmpeg_version || '运行环境' }}</small></div>
            <div><span>OpenList 上传</span><strong>{{ system?.upload?.enabled ? (system?.upload?.configured ? '已连接' : '未配置') : '未启用' }}</strong><small>{{ system?.upload?.active ? '正在上传' : '当前空闲' }}</small></div>
          </div>
        </div>
      </aside>
    </section>

    <section class="surface camera-surface">
      <header class="section-head camera-head"><div><span class="section-kicker">CAMERAS</span><h2>摄像头状态</h2><p>这里只显示运行状态和最近活动；进入 Live 后仍需手动开始画面。</p></div><span class="camera-total">{{ summary?.cameras.enabled ?? 0 }} 台已启用</span></header>
      <div class="camera-status-grid">
        <article v-for="camera in summary?.camera_health || []" :key="camera.camera_id" class="camera-row">
          <button type="button" class="camera-main" @click="primeLiveCamera(camera.camera_id)">
            <span class="camera-dot" :class="connectivityClass(camera)"></span>
            <span class="camera-identity"><strong>{{ camera.name }}</strong><small>{{ camera.ip }}</small></span>
            <span class="camera-facts"><span :class="connectivityClass(camera)">{{ connectivityLabel(camera.connectivity_status) }}</span><span :class="recorderClass(camera.recorder_state)">{{ recorderLabel(camera.recorder_state) }}</span><span class="source">{{ connectivitySourceLabel(camera) }}</span></span>
            <span class="camera-activity"><small>最近活动</small><strong>{{ latestActivityLabel(camera.camera_id) }}</strong></span>
            <span class="live-link">实时监控 ›</span>
          </button>
          <button type="button" class="camera-settings" aria-label="打开摄像头设置" @click="openCameraSettings(camera.camera_id)">•••</button>
          <div v-if="camera.abnormal && camera.last_error" class="camera-warning">{{ camera.last_error }}</div>
        </article>
        <div v-if="!summary?.camera_health?.length" class="camera-empty">暂无摄像头</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.protect-home{max-width:1760px;margin:0 auto;padding:24px 26px 34px;color:var(--nvr-text)}
.home-header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:18px}.home-heading{min-width:0}.eyebrow,.section-kicker{display:block;color:#647387;font-size:9px;font-weight:800;letter-spacing:.18em}.home-heading h1{margin:5px 0 4px;font-size:25px;line-height:1.2;font-weight:680;letter-spacing:-.025em}.home-heading p,.section-head p{margin:0;color:var(--nvr-muted);font-size:11px}
.health-pill{min-width:235px;display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface);cursor:pointer}.health-pill:hover,.health-pill:focus-visible{background:var(--nvr-surface-2);outline:none}.health-dot{width:8px;height:8px;flex:0 0 8px;border-radius:50%}.health-pill.healthy .health-dot{background:var(--nvr-green);box-shadow:0 0 0 4px rgba(46,204,138,.08)}.health-pill.attention .health-dot{background:var(--nvr-yellow);box-shadow:0 0 0 4px rgba(245,184,66,.08)}.health-pill div{display:flex;flex-direction:column;gap:2px}.health-pill strong{font-size:11px;font-weight:620}.health-pill small{color:#69788b;font-size:9px}
.status-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:12px;overflow:hidden;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.status-cell{min-height:66px;padding:13px 16px;border-right:1px solid var(--nvr-border)}.status-cell:last-child{border-right:0}.status-cell>span{display:block;margin-bottom:8px;color:#69788b;font-size:9px}.status-cell strong{font-size:18px;font-weight:660;letter-spacing:-.02em}.status-cell small{color:#738196;font-size:9px;font-weight:500}.attention-cell strong{color:var(--nvr-yellow)}
.surface{border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface);overflow:hidden}.home-primary-grid{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:12px;margin-bottom:12px}.section-head{min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 16px;border-bottom:1px solid var(--nvr-border)}.section-head.compact{min-height:60px}.section-head h2{margin:4px 0 3px;font-size:13px;font-weight:650}.quiet-link{border:0;padding:5px 0;background:transparent;color:#8d9aab;font:inherit;font-size:10px;cursor:pointer}.quiet-link:hover{color:var(--nvr-text)}
.activity-head-actions{display:flex;align-items:center;gap:12px}.activity-feed-state{display:flex;align-items:center;gap:5px;color:#718095;font-size:8px;white-space:nowrap}.activity-feed-state i{width:5px;height:5px;border-radius:50%;background:#58687b}.activity-feed-state.live i{background:var(--nvr-green);box-shadow:0 0 0 3px rgba(46,204,138,.07)}.activity-feed-state.fallback i{background:var(--nvr-yellow)}
.activity-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--nvr-border)}.activity-card{min-width:0;padding:0;border:0;background:var(--nvr-surface);color:inherit;text-align:left;cursor:pointer}.activity-card:hover,.activity-card:focus-visible{background:var(--nvr-surface-2);outline:none}.activity-card.fresh{animation:activity-arrive .9s ease-out}.activity-thumb{position:relative;display:block;aspect-ratio:16/9;overflow:hidden;background:#090c10}.activity-thumb img{width:100%;height:100%;display:block;object-fit:cover}.activity-placeholder{position:absolute;inset:0;display:grid;place-items:center;background:#0c1015}.activity-placeholder i,.empty-motion-mark{width:24px;height:18px;border:1px solid #34404f;border-radius:6px;position:relative}.activity-placeholder i::after,.empty-motion-mark::after{content:'';position:absolute;width:5px;height:5px;left:9px;top:6px;border-radius:50%;background:#526174}.activity-thumb time,.activity-badge{position:absolute;top:8px;padding:3px 5px;border-radius:4px;background:rgba(5,8,12,.74);color:#dce4ed;font-size:8px}.activity-thumb time{left:8px}.activity-badge{right:8px}.play-mark{position:absolute;left:50%;top:50%;width:30px;height:30px;display:grid;place-items:center;opacity:0;transform:translate(-50%,-50%);border-radius:50%;background:rgba(4,7,10,.68);color:#fff;font-size:9px;transition:opacity .15s}.activity-card:hover .play-mark,.activity-card:focus-visible .play-mark{opacity:1}.activity-copy{display:block;padding:10px 11px 11px}.activity-title,.activity-meta{display:flex;align-items:center;justify-content:space-between;gap:8px}.activity-title strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px;font-weight:620}.activity-title small,.activity-meta{color:#68778a;font-size:8px}.activity-meta{margin-top:6px}.activity-meta i{color:#8794a5;font-style:normal}.activity-empty{min-height:280px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;padding:24px;color:#6d7b8d;text-align:center}.activity-empty strong{color:#aeb8c4;font-size:11px}.activity-empty span{max-width:340px;font-size:9px}.activity-empty button{margin-top:5px;border:1px solid var(--nvr-border);border-radius:6px;padding:5px 10px;background:transparent;color:#8997a8;font-size:9px;cursor:pointer}
@keyframes activity-arrive{0%{box-shadow:inset 0 0 0 1px rgba(46,204,138,.42);background:rgba(46,204,138,.045)}100%{box-shadow:inset 0 0 0 1px rgba(46,204,138,0);background:var(--nvr-surface)}}
.system-body{padding:16px}.storage-line{padding-bottom:17px;border-bottom:1px solid var(--nvr-border)}.storage-title{display:flex;align-items:baseline;justify-content:space-between}.storage-line span{color:#718095;font-size:9px}.storage-line strong{font-size:20px;font-weight:660}.storage-track{height:5px;margin:11px 0 8px;overflow:hidden;border-radius:999px;background:#252d38}.storage-track i{display:block;height:100%;border-radius:inherit;background:#71849b}.storage-copy{display:flex;justify-content:space-between}.system-list>div{display:grid;grid-template-columns:1fr auto;gap:4px 12px;padding:13px 0;border-bottom:1px solid var(--nvr-border)}.system-list>div:last-child{border-bottom:0;padding-bottom:0}.system-list span{color:#718095;font-size:9px}.system-list strong{font-size:10px;font-weight:600}.system-list small{grid-column:1/-1;color:#657386;font-size:8px}
.camera-head{min-height:70px}.camera-total{color:#6d7c8f;font-size:9px}.camera-status-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--nvr-border)}.camera-row{position:relative;min-width:0;background:var(--nvr-surface)}.camera-row:hover{background:var(--nvr-surface-2)}.camera-main{width:100%;min-height:68px;display:grid;grid-template-columns:8px minmax(100px,1fr) auto minmax(90px,.65fr) auto;align-items:center;gap:10px;padding:11px 42px 11px 14px;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer}.camera-main:focus-visible{outline:1px solid #506178;outline-offset:-2px}.camera-dot{width:7px;height:7px;border-radius:50%}.camera-dot.success{background:var(--nvr-green)}.camera-dot.warning{background:var(--nvr-yellow)}.camera-dot.danger{background:var(--nvr-red)}.camera-dot.muted{background:#536173}.camera-identity,.camera-activity{min-width:0;display:flex;flex-direction:column;gap:3px}.camera-identity strong,.camera-activity strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px;font-weight:620}.camera-identity small,.camera-activity small{color:#667589;font-size:8px}.camera-facts{display:flex;gap:5px}.camera-facts span{padding:3px 5px;border-radius:4px;background:rgba(255,255,255,.025);color:#728196;font-size:8px}.camera-facts .success{color:var(--nvr-green)}.camera-facts .warning{color:var(--nvr-yellow)}.camera-facts .danger{color:var(--nvr-red)}.camera-facts .muted{color:#718095}.camera-facts .source{color:#667589;background:transparent;padding-left:1px;padding-right:1px}.live-link{color:#8795a7;font-size:9px}.camera-settings{position:absolute;right:10px;top:19px;width:26px;height:26px;border:0;border-radius:6px;background:transparent;color:#657386;cursor:pointer}.camera-settings:hover{background:rgba(255,255,255,.045);color:#aab5c1}.camera-warning{padding:0 14px 9px 32px;overflow:hidden;color:var(--nvr-yellow);font-size:8px;white-space:nowrap;text-overflow:ellipsis}.camera-empty{grid-column:1/-1;padding:34px;background:var(--nvr-surface);color:#68778a;text-align:center;font-size:10px}
@media(prefers-reduced-motion:reduce){.activity-card.fresh{animation:none}}
@media(max-width:1320px){.activity-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.home-primary-grid{grid-template-columns:minmax(0,1fr) 300px}.camera-main{grid-template-columns:8px minmax(90px,1fr) auto auto}.camera-activity{display:none}}
@media(max-width:980px){.home-primary-grid{grid-template-columns:1fr}.system-list{display:grid;grid-template-columns:1fr 1fr;gap:0 18px}.camera-status-grid{grid-template-columns:1fr}}
@media(max-width:720px){.protect-home{padding:15px}.home-header{align-items:flex-start;flex-direction:column}.health-pill{width:100%}.status-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.status-cell:nth-child(2){border-right:0}.status-cell:nth-child(-n+2){border-bottom:1px solid var(--nvr-border)}.activity-grid{grid-template-columns:1fr}.section-head{align-items:flex-start}.activity-head-actions{align-items:flex-end;flex-direction:column;gap:5px}.camera-main{grid-template-columns:8px minmax(90px,1fr) auto}.camera-activity,.live-link{display:none}.home-heading h1{font-size:22px}}
</style>