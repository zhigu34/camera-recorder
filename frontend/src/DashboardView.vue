<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import {
  Bell,
  CircleCheckFilled,
  Cloudy,
  DataLine,
  VideoCamera,
  WarningFilled,
} from '@element-plus/icons-vue'

interface CameraHealth {
  camera_id: number
  name: string
  ip: string
  enabled: boolean
  expected_recording: boolean
  connectivity_status: 'unknown' | 'online' | 'offline'
  recorder_state: string
  schedule_state: string
  state: string
  abnormal: boolean
  restart_count: number
  last_error?: string | null
}

interface HealthSummary {
  generated_at: string
  uptime_seconds: number
  cameras: {
    total: number
    enabled: number
    recording: number
    reconnecting: number
    abnormal: number
    online: number
    offline: number
    unknown: number
  }
  recordings_24h: {
    segments: number
    unhealthy_segments: number
    failed_segments: number
  }
  uploads: Record<string, number>
  storage: {
    total_bytes: number
    used_bytes: number
    free_bytes: number
    used_percent: number
    state: 'healthy' | 'warning' | 'critical'
  }
  camera_health: CameraHealth[]
}

interface SystemStatus {
  ffmpeg?: { setts_available?: boolean; ffmpeg_version?: string | null }
  upload?: { enabled: boolean; configured: boolean; active: boolean; provider?: string }
  storage_cleanup?: { last_error?: string | null }
}

interface EventItem {
  id: number
  level: string
  category: string
  code: string
  message: string
  camera_id?: number | null
  created_at: string
}

const loading = ref(false)
const summary = ref<HealthSummary | null>(null)
const system = ref<SystemStatus | null>(null)
const events = ref<EventItem[]>([])
let timer: number | null = null

const pendingUploads = computed(() => {
  const rows = summary.value?.uploads || {}
  return (rows.pending || 0) + (rows.uploading || 0) + (rows.retry_wait || 0)
})
const uploadFailures = computed(() => summary.value?.uploads?.failed || 0)
const overallHealthy = computed(() =>
  Boolean(
    summary.value &&
    summary.value.cameras.abnormal === 0 &&
    summary.value.storage.state !== 'critical' &&
    uploadFailures.value === 0 &&
    system.value?.ffmpeg?.setts_available !== false,
  ),
)
const storageProgressStatus = computed(() => {
  if (summary.value?.storage.state === 'critical') return 'exception'
  if (summary.value?.storage.state === 'warning') return 'warning'
  return 'success'
})

function bytes(value?: number) {
  const bytes = value || 0
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(2)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  return `${(bytes / 1024 ** 2).toFixed(0)} MB`
}
function uptime(value?: number) {
  const seconds = value || 0
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  return days ? `${days}天 ${hours}小时` : `${hours}小时`
}
function eventTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
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
function connectivityLabel(state: string) {
  if (state === 'online') return '在线'
  if (state === 'offline') return '离线'
  return '未检测'
}
function connectivityClass(camera: CameraHealth) {
  if (!camera.enabled) return 'muted'
  if (camera.connectivity_status === 'online') return 'success'
  if (camera.connectivity_status === 'offline') return 'danger'
  return 'warning'
}
function scheduleLabel(state: string) {
  if (state === 'automatic') return '自动录像'
  if (state === 'in_window') return '计划时段内'
  if (state === 'scheduled') return '等待计划时段'
  if (state === 'manual_override') return '手动运行'
  if (state === 'manual_paused') return '手动暂停'
  if (state === 'probe_required') return '需要检测参数'
  if (state === 'error') return '计划启动失败'
  if (state === 'global_disabled') return '全局自动启动关闭'
  return '未启用自动录像'
}
function eventClass(level: string) {
  if (level === 'critical' || level === 'error') return 'danger'
  if (level === 'warning') return 'warning'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    const [healthRes, systemRes, eventRes] = await Promise.all([
      axios.get<HealthSummary>('/api/health/summary'),
      axios.get<SystemStatus>('/api/system/status'),
      axios.get<EventItem[]>('/api/events?limit=8'),
    ])
    summary.value = healthRes.data
    system.value = systemRes.data
    events.value = eventRes.data
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  timer = window.setInterval(load, 10000)
})
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <div class="dashboard-page" v-loading="loading">
    <section class="dashboard-head">
      <div>
        <div class="eyebrow">OPERATIONS OVERVIEW</div>
        <h1>监控系统总览</h1>
        <p>录像链路、存储、上传和摄像头状态集中视图</p>
      </div>
      <div class="health-badge" :class="overallHealthy ? 'healthy' : 'warning'">
        <CircleCheckFilled v-if="overallHealthy" />
        <WarningFilled v-else />
        <div>
          <strong>{{ overallHealthy ? '全部系统正常' : '存在需要关注的项目' }}</strong>
          <span>已运行 {{ uptime(summary?.uptime_seconds) }}</span>
        </div>
      </div>
    </section>

    <section class="metric-grid">
      <article class="metric-card primary">
        <div class="metric-icon"><VideoCamera /></div>
        <div class="metric-copy"><span>正在录像</span><strong>{{ summary?.cameras.recording ?? '-' }}<small>/ {{ summary?.cameras.enabled ?? '-' }}</small></strong></div>
        <div class="metric-foot">在线 {{ summary?.cameras.online ?? '-' }} · 离线 {{ summary?.cameras.offline ?? '-' }}</div>
      </article>
      <article class="metric-card">
        <div class="metric-icon"><DataLine /></div>
        <div class="metric-copy"><span>24h 录像片段</span><strong>{{ summary?.recordings_24h.segments ?? '-' }}</strong></div>
        <div class="metric-foot"><b :class="{ danger: (summary?.recordings_24h.unhealthy_segments || 0) > 0 }">{{ summary?.recordings_24h.unhealthy_segments ?? 0 }}</b> 个异常片段</div>
      </article>
      <article class="metric-card">
        <div class="metric-icon"><Cloudy /></div>
        <div class="metric-copy"><span>上传队列</span><strong>{{ pendingUploads }}</strong></div>
        <div class="metric-foot"><b :class="{ danger: uploadFailures > 0 }">{{ uploadFailures }}</b> 个最终失败</div>
      </article>
      <article class="metric-card">
        <div class="metric-icon"><Bell /></div>
        <div class="metric-copy"><span>当前异常</span><strong :class="{ danger: (summary?.cameras.abnormal || 0) > 0 }">{{ summary?.cameras.abnormal ?? '-' }}</strong></div>
        <div class="metric-foot">{{ summary?.cameras.reconnecting ?? 0 }} 路正在重连 · {{ summary?.cameras.unknown ?? 0 }} 路未检测</div>
      </article>
    </section>

    <section class="dashboard-grid">
      <article class="panel camera-panel">
        <div class="panel-head">
          <div><span class="panel-kicker">CAMERAS</span><h2>摄像头运行状态</h2></div>
          <span class="panel-meta">10 秒自动刷新</span>
        </div>
        <div class="camera-grid">
          <div v-for="camera in summary?.camera_health || []" :key="camera.camera_id" class="camera-tile">
            <div class="camera-title">
              <span class="camera-dot" :class="connectivityClass(camera)"></span>
              <div><strong>{{ camera.name }}</strong><span>{{ camera.ip }}</span></div>
              <span class="camera-state" :class="connectivityClass(camera)">{{ connectivityLabel(camera.connectivity_status) }}</span>
              <span class="camera-state" :class="recorderClass(camera.recorder_state)">{{ recorderLabel(camera.recorder_state) }}</span>
            </div>
            <div class="camera-detail">
              <span>{{ scheduleLabel(camera.schedule_state) }}</span>
              <span>重连 {{ camera.restart_count }}</span>
              <span v-if="camera.abnormal" class="danger">需要关注</span>
            </div>
            <div v-if="camera.last_error && camera.abnormal" class="camera-error">{{ camera.last_error }}</div>
          </div>
          <div v-if="!summary?.camera_health?.length" class="empty-state">暂无摄像头</div>
        </div>
      </article>

      <aside class="right-column">
        <article class="panel storage-panel">
          <div class="panel-head compact">
            <div><span class="panel-kicker">STORAGE</span><h2>录像存储</h2></div>
            <span class="storage-value">{{ summary?.storage.used_percent ?? '-' }}%</span>
          </div>
          <el-progress
            :percentage="summary?.storage.used_percent || 0"
            :status="storageProgressStatus"
            :stroke-width="8"
            :show-text="false"
          />
          <div class="storage-stats">
            <div><span>已使用</span><strong>{{ bytes(summary?.storage.used_bytes) }}</strong></div>
            <div><span>剩余</span><strong>{{ bytes(summary?.storage.free_bytes) }}</strong></div>
          </div>
          <div class="service-row"><span>FFmpeg / setts</span><b :class="system?.ffmpeg?.setts_available ? 'ok' : 'bad'">{{ system?.ffmpeg?.setts_available ? '正常' : '异常' }}</b></div>
          <div class="service-row"><span>OpenList 上传</span><b :class="system?.upload?.enabled && system?.upload?.configured ? 'ok' : 'neutral'">{{ system?.upload?.enabled ? system?.upload?.configured ? '已连接' : '未配置' : '未启用' }}</b></div>
        </article>

        <article class="panel event-panel">
          <div class="panel-head compact"><div><span class="panel-kicker">ACTIVITY</span><h2>最近事件</h2></div></div>
          <div class="event-list">
            <div v-for="event in events" :key="event.id" class="event-row">
              <span class="event-marker" :class="eventClass(event.level)"></span>
              <div class="event-content"><strong>{{ event.message }}</strong><span>{{ eventTime(event.created_at) }} · {{ event.category }}</span></div>
            </div>
            <div v-if="!events.length" class="empty-state compact">暂无事件</div>
          </div>
        </article>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.dashboard-page { padding: 26px; max-width: 1760px; margin: 0 auto; }
.dashboard-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 22px; }
.eyebrow, .panel-kicker { color: #586a80; font-size: 9px; font-weight: 800; letter-spacing: .17em; }
.dashboard-head h1 { margin: 5px 0 5px; font-size: 25px; font-weight: 680; letter-spacing: -.025em; }
.dashboard-head p { margin: 0; color: var(--nvr-muted); font-size: 12px; }
.health-badge { min-width: 225px; display: flex; align-items: center; gap: 11px; padding: 11px 14px; border: 1px solid var(--nvr-border); border-radius: 10px; background: var(--nvr-surface); }
.health-badge > svg { width: 20px; }
.health-badge > div { display: flex; flex-direction: column; gap: 3px; }
.health-badge strong { font-size: 12px; }
.health-badge span { color: var(--nvr-muted); font-size: 10px; }
.health-badge.healthy > svg { color: var(--nvr-green); }.health-badge.warning > svg { color: var(--nvr-yellow); }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }
.metric-card { position: relative; min-height: 126px; padding: 17px; overflow: hidden; border: 1px solid var(--nvr-border); border-radius: 10px; background: var(--nvr-surface); }
.metric-card.primary { background: linear-gradient(145deg, rgba(76,141,255,.15), rgba(20,26,34,.95) 58%); border-color: rgba(76,141,255,.2); }
.metric-icon { position: absolute; right: 16px; top: 16px; width: 28px; height: 28px; display: grid; place-items: center; color: #61728a; border: 1px solid var(--nvr-border); border-radius: 8px; background: rgba(255,255,255,.02); }
.metric-card.primary .metric-icon { color: var(--nvr-blue); }.metric-icon :deep(svg) { width: 15px; }
.metric-copy { display: flex; flex-direction: column; gap: 8px; }.metric-copy span { color: var(--nvr-muted); font-size: 11px; }.metric-copy strong { font-size: 30px; line-height: 1; letter-spacing: -.04em; font-weight: 670; }.metric-copy small { margin-left: 5px; color: #647287; font-size: 13px; font-weight: 500; }
.metric-foot { position: absolute; left: 17px; bottom: 15px; color: #69788b; font-size: 10px; }.metric-foot b { color: #9aa7b7; }.danger { color: var(--nvr-red) !important; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(310px, .65fr); gap: 12px; }
.panel { border: 1px solid var(--nvr-border); border-radius: 10px; background: var(--nvr-surface); }
.panel-head { min-height: 66px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 18px; border-bottom: 1px solid var(--nvr-border); }.panel-head.compact { min-height: 60px; }
.panel-head h2 { margin: 4px 0 0; font-size: 13px; font-weight: 640; }.panel-meta { color: #657488; font-size: 10px; }
.camera-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--nvr-border); }
.camera-tile { min-height: 92px; padding: 14px 16px; background: var(--nvr-surface); }.camera-tile:hover { background: var(--nvr-surface-2); }
.camera-title { display: flex; align-items: center; gap: 7px; }.camera-title > div { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; }.camera-title strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }.camera-title span { color: #647287; font-size: 10px; }
.camera-dot { flex: 0 0 7px; width: 7px; height: 7px; border-radius: 50%; }.camera-dot.success { background: var(--nvr-green); box-shadow: 0 0 0 3px rgba(46,204,138,.08); }.camera-dot.warning { background: var(--nvr-yellow); }.camera-dot.danger { background: var(--nvr-red); }.camera-dot.muted { background: #526071; }
.camera-state { flex: 0 0 auto; padding: 3px 6px; border-radius: 5px; background: rgba(255,255,255,.035); }.camera-state.success { color: var(--nvr-green); }.camera-state.warning { color: var(--nvr-yellow); }.camera-state.danger { color: var(--nvr-red); }.camera-state.muted { color: #718095; }
.camera-detail { display: flex; gap: 15px; margin: 11px 0 0 16px; color: #637084; font-size: 9px; }.camera-error { margin: 8px 0 0 16px; overflow: hidden; color: var(--nvr-red); font-size: 9px; white-space: nowrap; text-overflow: ellipsis; }
.right-column { display: flex; flex-direction: column; gap: 12px; }.storage-panel { padding-bottom: 15px; }.storage-panel :deep(.el-progress) { margin: 18px 18px 14px; }.storage-value { font-size: 20px; font-weight: 670; }
.storage-stats { display: grid; grid-template-columns: 1fr 1fr; padding: 0 18px 14px; gap: 10px; }.storage-stats div { display: flex; flex-direction: column; gap: 3px; }.storage-stats span { color: #647287; font-size: 9px; }.storage-stats strong { font-size: 12px; }
.service-row { display: flex; justify-content: space-between; padding: 9px 18px 0; border-top: 1px solid rgba(255,255,255,.035); color: #788699; font-size: 10px; }.service-row b.ok { color: var(--nvr-green); }.service-row b.bad { color: var(--nvr-red); }.service-row b.neutral { color: #788699; }
.event-list { padding: 5px 0; }.event-row { display: flex; gap: 10px; padding: 10px 16px; }.event-row + .event-row { border-top: 1px solid rgba(255,255,255,.035); }.event-marker { flex: 0 0 6px; width: 6px; height: 6px; margin-top: 4px; border-radius: 50%; }.event-marker.danger { background: var(--nvr-red); }.event-marker.warning { background: var(--nvr-yellow); }.event-marker.info { background: #577291; }.event-content { min-width: 0; display: flex; flex-direction: column; gap: 4px; }.event-content strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; font-weight: 560; }.event-content span { color: #5f6e81; font-size: 9px; }
.empty-state { grid-column: 1/-1; padding: 34px; text-align: center; color: #657488; font-size: 11px; background: var(--nvr-surface); }.empty-state.compact { padding: 20px; }
@media(max-width:1200px){.metric-grid{grid-template-columns:repeat(2,1fr)}.dashboard-grid{grid-template-columns:1fr}.right-column{display:grid;grid-template-columns:1fr 1fr}}
@media(max-width:760px){.dashboard-page{padding:14px}.dashboard-head{align-items:flex-start;flex-direction:column}.health-badge{width:100%}.metric-grid,.camera-grid,.right-column{grid-template-columns:1fr}.dashboard-head h1{font-size:21px}.camera-state:nth-last-child(1){display:none}}
</style>
