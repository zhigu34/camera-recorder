<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Refresh, WarningFilled } from '@element-plus/icons-vue'

interface RecordingStats {
  segments: number
  unhealthy_segments: number
  failed_segments: number
  warning_count: number
  timestamp_warning_count: number
  network_warning_count: number
}

interface CameraHealth {
  camera_id: number
  name: string
  ip: string
  enabled: boolean
  expected_recording: boolean
  connectivity_status: 'unknown' | 'online' | 'offline'
  recorder_state: string
  schedule_state: string
  abnormal: boolean
  restart_count: number
  started_at?: string | null
  last_error?: string | null
  recordings_24h: RecordingStats
}

interface StorageCleanup {
  running: boolean
  last_run_at: string | null
  last_result: string | null
  deleted_files: number
  freed_bytes: number
  last_error: string | null
}

interface HealthSnapshot {
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
  recordings_24h: RecordingStats
  uploads: Record<string, number>
  storage: {
    total_bytes: number
    used_bytes: number
    free_bytes: number
    used_percent: number
    state: 'healthy' | 'warning' | 'critical'
    cleanup: StorageCleanup
  }
  camera_health: CameraHealth[]
}

interface CameraTrend {
  camera_id: number
  name: string
  ip: string
  monitored: boolean
  observed_minutes: number
  online_rate: number | null
  recording_segments: number
  complete_segments: number
  recording_completeness: number | null
}

interface HealthTrends {
  generated_at: string
  overall: {
    monitored_cameras: number
    samples: number
    online_rate: number | null
    recording_segments: number
    complete_segments: number
    recording_completeness: number | null
  }
  cameras: CameraTrend[]
}

type Verdict = 'pass' | 'fail' | 'collecting' | 'ignored'

interface StabilityCamera {
  camera_id: number
  name: string
  ip: string
  monitored: boolean
  verdict: Verdict
  reasons: string[]
  sample_coverage: number
  online_rate: number | null
  recording_completeness: number | null
  ffmpeg_failures: number
  outage_count: number
  longest_offline_seconds: number
  current_offline_seconds: number
}

interface StabilityReport {
  generated_at: string
  hours: number
  overall: {
    verdict: Exclude<Verdict, 'ignored'>
    monitored_cameras: number
    passed_cameras: number
    failed_cameras: number
    collecting_cameras: number
    online_rate: number | null
    recording_completeness: number | null
    ffmpeg_failures: number
    outage_count: number
    longest_offline_seconds: number
  }
  cameras: StabilityCamera[]
}

const snapshot = ref<HealthSnapshot | null>(null)
const trends = ref<HealthTrends | null>(null)
const stability = ref<StabilityReport | null>(null)
const stabilityWindow = ref(24)
const loading = ref(false)
const wsConnected = ref(false)
let socket: WebSocket | null = null
let reconnectTimer: number | null = null
let refreshTimer: number | null = null
let destroyed = false

const pendingUploads = computed(() => {
  const value = snapshot.value?.uploads || {}
  return (value.pending || 0) + (value.uploading || 0) + (value.retry_wait || 0)
})
const monitoredTrends = computed(() => (trends.value?.cameras || []).filter((item) => item.monitored))
const monitoredStability = computed(() => (stability.value?.cameras || []).filter((item) => item.monitored))

function formatBytes(value?: number) {
  const bytes = value || 0
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(2)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`
  return `${bytes} B`
}
function formatDuration(value?: number) {
  const seconds = Math.max(0, Math.floor(value || 0))
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return `${days}天 ${hours}小时`
  if (hours) return `${hours}小时 ${minutes}分`
  if (minutes) return `${minutes}分`
  return `${seconds}秒`
}
function formatTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
function rate(value?: number | null) {
  return value === null || value === undefined ? '-' : `${value.toFixed(2)}%`
}
function rateType(value?: number | null) {
  if (value === null || value === undefined) return 'info'
  if (value >= 99.9) return 'success'
  if (value >= 99) return 'warning'
  return 'danger'
}
function connectivityLabel(value: string) {
  if (value === 'online') return '在线'
  if (value === 'offline') return '离线'
  return '未检测'
}
function connectivityType(value: string) {
  if (value === 'online') return 'success'
  if (value === 'offline') return 'danger'
  return 'warning'
}
function recorderLabel(value: string) {
  if (value === 'RECORDING') return '录像中'
  if (value === 'STARTING') return '启动中'
  if (value === 'RECONNECTING') return '重连中'
  if (value === 'STOPPING') return '停止中'
  return '未录像'
}
function recorderType(value: string) {
  if (value === 'RECORDING') return 'success'
  if (['STARTING', 'RECONNECTING', 'STOPPING'].includes(value)) return 'warning'
  return 'info'
}
function scheduleLabel(value: string) {
  if (value === 'automatic') return '自动录像'
  if (value === 'in_window') return '计划时段内'
  if (value === 'scheduled') return '等待计划时段'
  if (value === 'manual_override') return '手动运行'
  if (value === 'manual_paused') return '手动暂停'
  if (value === 'probe_required') return '需要检测参数'
  if (value === 'error') return '计划启动失败'
  if (value === 'global_disabled') return '全局自动启动关闭'
  return '未启用自动录像'
}
function scheduleType(value: string) {
  if (['automatic', 'in_window', 'manual_override'].includes(value)) return 'success'
  if (['probe_required', 'error'].includes(value)) return 'danger'
  if (value === 'manual_paused') return 'warning'
  return 'info'
}
function verdictLabel(value: Verdict) {
  if (value === 'pass') return '通过'
  if (value === 'fail') return '未通过'
  if (value === 'collecting') return '采集中'
  return '未监控'
}
function verdictType(value: Verdict) {
  if (value === 'pass') return 'success'
  if (value === 'fail') return 'danger'
  if (value === 'collecting') return 'warning'
  return 'info'
}

async function loadAll(showMessage = false) {
  loading.value = true
  try {
    const [snapshotRes, trendsRes, stabilityRes] = await Promise.all([
      axios.get<HealthSnapshot>('/api/health/summary'),
      axios.get<HealthTrends>('/api/health/trends', { params: { hours: 24, bucket_minutes: 60 } }),
      axios.get<StabilityReport>('/api/health/stability', { params: { hours: stabilityWindow.value } }),
    ])
    snapshot.value = snapshotRes.data
    trends.value = trendsRes.data
    stability.value = stabilityRes.data
    if (showMessage) ElMessage.success('健康状态已刷新')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '健康状态加载失败')
  } finally {
    loading.value = false
  }
}

async function changeStabilityWindow() {
  try {
    stability.value = (await axios.get<StabilityReport>('/api/health/stability', { params: { hours: stabilityWindow.value } })).data
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '稳定性数据加载失败')
  }
}

function scheduleReconnect() {
  if (destroyed || reconnectTimer !== null) return
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    connectWebSocket()
  }, 3000)
}
function connectWebSocket() {
  if (destroyed) return
  if (socket) {
    socket.onclose = null
    socket.close()
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  socket = new WebSocket(`${protocol}//${window.location.host}/ws/status`)
  socket.onopen = () => { wsConnected.value = true }
  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data)
      if (message.type === 'health.snapshot' && message.data) snapshot.value = message.data as HealthSnapshot
    } catch { /* next snapshot will recover */ }
  }
  socket.onerror = () => { wsConnected.value = false }
  socket.onclose = () => {
    wsConnected.value = false
    socket = null
    scheduleReconnect()
  }
}

onMounted(() => {
  void loadAll()
  connectWebSocket()
  refreshTimer = window.setInterval(() => void loadAll(false), 60_000)
})
onBeforeUnmount(() => {
  destroyed = true
  if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
  if (socket) {
    socket.onclose = null
    socket.close()
  }
})
</script>

<template>
  <section class="health-v2" v-loading="loading && !snapshot">
    <div class="page-head">
      <div class="realtime-pill" :class="{ online: wsConnected }"><i></i>{{ wsConnected ? '实时状态已连接' : '实时状态重连中' }}</div>
      <el-button :icon="Refresh" @click="loadAll(true)">刷新</el-button>
    </div>

    <template v-if="snapshot">
      <div class="metrics">
        <article><span>连接在线</span><strong>{{ snapshot.cameras.online }}<small>/ {{ snapshot.cameras.total }}</small></strong><em>{{ snapshot.cameras.offline }} 离线 · {{ snapshot.cameras.unknown }} 未检测</em></article>
        <article><span>录像中</span><strong>{{ snapshot.cameras.recording }}<small>/ {{ snapshot.cameras.enabled }}</small></strong><em>{{ snapshot.cameras.reconnecting }} 路启动/重连</em></article>
        <article :class="{ alert: snapshot.cameras.abnormal > 0 }"><span>需要关注</span><strong>{{ snapshot.cameras.abnormal }}</strong><em>连接或录像链路异常</em></article>
        <article><span>24h 录像片段</span><strong>{{ snapshot.recordings_24h.segments }}</strong><em>{{ snapshot.recordings_24h.unhealthy_segments }} 个异常片段</em></article>
        <article><span>上传待处理</span><strong>{{ pendingUploads }}</strong><em>{{ snapshot.uploads.failed || 0 }} 个最终失败</em></article>
        <article :class="{ alert: snapshot.storage.state === 'critical' }"><span>磁盘占用</span><strong>{{ snapshot.storage.used_percent }}<small>%</small></strong><em>{{ formatBytes(snapshot.storage.free_bytes) }} 可用</em></article>
      </div>

      <article class="panel camera-panel">
        <div class="panel-head"><div><strong>摄像头实时状态</strong><span>连接、录像、计划三条状态链独立展示</span></div><span>服务运行 {{ formatDuration(snapshot.uptime_seconds) }}</span></div>
        <el-table :data="snapshot.camera_health" empty-text="暂无摄像头" class="state-table">
          <el-table-column prop="name" label="摄像头" min-width="150" fixed="left" />
          <el-table-column prop="ip" label="IP" width="140" />
          <el-table-column label="连接" width="105">
            <template #default="{ row }"><el-tag :type="connectivityType(row.connectivity_status)">{{ connectivityLabel(row.connectivity_status) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="录像" width="110">
            <template #default="{ row }"><el-tag :type="recorderType(row.recorder_state)">{{ recorderLabel(row.recorder_state) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="计划状态" min-width="150">
            <template #default="{ row }"><el-tag :type="scheduleType(row.schedule_state)" effect="plain">{{ scheduleLabel(row.schedule_state) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="期望录像" width="90"><template #default="{ row }">{{ row.expected_recording ? '是' : '否' }}</template></el-table-column>
          <el-table-column prop="restart_count" label="重连" width="75" sortable />
          <el-table-column label="24h片段" width="90"><template #default="{ row }">{{ row.recordings_24h.segments }}</template></el-table-column>
          <el-table-column label="最后错误" min-width="260" show-overflow-tooltip><template #default="{ row }">{{ row.last_error || '-' }}</template></el-table-column>
          <el-table-column label="健康" width="90" fixed="right"><template #default="{ row }"><el-tag :type="row.abnormal ? 'danger' : 'success'">{{ row.abnormal ? '关注' : '正常' }}</el-tag></template></el-table-column>
        </el-table>
      </article>

      <div class="two-column">
        <article class="panel">
          <div class="panel-head"><div><strong>24h 录像可靠性</strong><span>历史字段 online_rate 表示期望录像时段内 Recorder 可用率</span></div></div>
          <div v-if="trends" class="reliability-grid">
            <div><span>录像可用率</span><strong><el-tag size="large" :type="rateType(trends.overall.online_rate)">{{ rate(trends.overall.online_rate) }}</el-tag></strong></div>
            <div><span>录像完整率</span><strong><el-tag size="large" :type="rateType(trends.overall.recording_completeness)">{{ rate(trends.overall.recording_completeness) }}</el-tag></strong></div>
            <div><span>监控摄像头</span><strong>{{ trends.overall.monitored_cameras }}</strong></div>
            <div><span>采样点</span><strong>{{ trends.overall.samples }}</strong></div>
          </div>
          <el-table v-if="trends" :data="monitoredTrends" size="small" empty-text="暂无自动录像样本">
            <el-table-column prop="name" label="摄像头" min-width="130" />
            <el-table-column label="录像可用率" width="120"><template #default="{ row }"><el-tag :type="rateType(row.online_rate)">{{ rate(row.online_rate) }}</el-tag></template></el-table-column>
            <el-table-column label="完整率" width="105"><template #default="{ row }">{{ rate(row.recording_completeness) }}</template></el-table-column>
            <el-table-column prop="observed_minutes" label="采样分钟" width="95" />
          </el-table>
        </article>

        <article class="panel storage-panel">
          <div class="panel-head"><div><strong>磁盘与自动保护</strong><span>{{ snapshot.storage.state }} · 最近检查 {{ formatTime(snapshot.storage.cleanup.last_run_at) }}</span></div></div>
          <div class="storage-number">{{ snapshot.storage.used_percent }}%</div>
          <el-progress :percentage="snapshot.storage.used_percent" :status="snapshot.storage.state === 'critical' ? 'exception' : snapshot.storage.state === 'warning' ? 'warning' : 'success'" :show-text="false" />
          <div class="storage-detail"><span>已用 {{ formatBytes(snapshot.storage.used_bytes) }}</span><span>剩余 {{ formatBytes(snapshot.storage.free_bytes) }}</span><span>总计 {{ formatBytes(snapshot.storage.total_bytes) }}</span></div>
          <div v-if="snapshot.storage.cleanup.last_error" class="error-box"><WarningFilled />{{ snapshot.storage.cleanup.last_error }}</div>
        </article>
      </div>

      <article v-if="stability" class="panel stability-panel">
        <div class="panel-head">
          <div><strong>稳定性验收</strong><span>FFmpeg 连续失败、断流与录像完整性综合验收</span></div>
          <div class="panel-actions"><el-tag :type="verdictType(stability.overall.verdict)">{{ verdictLabel(stability.overall.verdict) }}</el-tag><el-radio-group v-model="stabilityWindow" size="small" @change="changeStabilityWindow"><el-radio-button :value="24">24h</el-radio-button><el-radio-button :value="72">72h</el-radio-button></el-radio-group></div>
        </div>
        <div class="stability-summary"><span>通过 <b>{{ stability.overall.passed_cameras }}/{{ stability.overall.monitored_cameras }}</b></span><span>FFmpeg 异常 <b>{{ stability.overall.ffmpeg_failures }}</b></span><span>断流 <b>{{ stability.overall.outage_count }}</b></span><span>最长断流 <b>{{ formatDuration(stability.overall.longest_offline_seconds) }}</b></span></div>
        <el-table :data="monitoredStability" size="small" empty-text="暂无稳定性样本">
          <el-table-column prop="name" label="摄像头" min-width="140" />
          <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="verdictType(row.verdict)">{{ verdictLabel(row.verdict) }}</el-tag></template></el-table-column>
          <el-table-column label="覆盖率" width="100"><template #default="{ row }">{{ rate(row.sample_coverage) }}</template></el-table-column>
          <el-table-column label="录像可用率" width="115"><template #default="{ row }">{{ rate(row.online_rate) }}</template></el-table-column>
          <el-table-column label="完整率" width="100"><template #default="{ row }">{{ rate(row.recording_completeness) }}</template></el-table-column>
          <el-table-column prop="ffmpeg_failures" label="FFmpeg" width="80" />
          <el-table-column prop="outage_count" label="断流" width="70" />
          <el-table-column label="最长断流" width="105"><template #default="{ row }">{{ formatDuration(row.longest_offline_seconds) }}</template></el-table-column>
          <el-table-column label="原因" min-width="220" show-overflow-tooltip><template #default="{ row }">{{ row.reasons.length ? row.reasons.join('；') : '-' }}</template></el-table-column>
        </el-table>
      </article>

      <div class="snapshot-time">实时快照 {{ formatTime(snapshot.generated_at) }}</div>
    </template>
  </section>
</template>

<style scoped>
.health-v2{max-width:1760px;margin:0 auto;padding:22px;color:var(--nvr-text)}
.page-head{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-bottom:14px}.realtime-pill{display:flex;align-items:center;gap:7px;margin-right:auto;color:var(--nvr-yellow);font-size:10px}.realtime-pill i{width:7px;height:7px;border-radius:50%;background:currentColor}.realtime-pill.online{color:var(--nvr-green)}
.metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;margin-bottom:10px}.metrics article{min-height:102px;padding:14px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.metrics article.alert{border-color:rgba(240,93,94,.35)}.metrics span,.metrics em{display:block;color:var(--nvr-muted);font-size:10px;font-style:normal}.metrics strong{display:block;margin:9px 0 7px;font-size:25px;line-height:1}.metrics small{margin-left:4px;color:#66758a;font-size:12px;font-weight:500}.metrics article.alert strong{color:var(--nvr-red)}
.panel{margin-top:10px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface);overflow:hidden}.panel-head{min-height:60px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 15px;border-bottom:1px solid var(--nvr-border)}.panel-head>div:first-child{display:flex;flex-direction:column;gap:4px}.panel-head strong{font-size:12px}.panel-head span{color:var(--nvr-muted);font-size:9px}.panel-actions{display:flex!important;flex-direction:row!important;align-items:center;gap:8px}.state-table{width:100%}
.two-column{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(300px,.6fr);gap:10px}.reliability-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--nvr-border);border-bottom:1px solid var(--nvr-border)}.reliability-grid>div{padding:14px;background:var(--nvr-surface);display:flex;flex-direction:column;gap:7px}.reliability-grid span{color:var(--nvr-muted);font-size:9px}.reliability-grid strong{font-size:18px}.storage-panel{padding-bottom:16px}.storage-number{padding:18px 16px 8px;font-size:30px;font-weight:680}.storage-panel :deep(.el-progress){margin:0 16px 16px}.storage-detail{display:flex;gap:18px;flex-wrap:wrap;padding:0 16px;color:var(--nvr-muted);font-size:10px}.error-box{display:flex;align-items:flex-start;gap:8px;margin:14px 16px 0;padding:9px;color:var(--nvr-red);background:rgba(240,93,94,.06);border:1px solid rgba(240,93,94,.16);border-radius:7px;font-size:10px}.error-box :deep(svg){flex:0 0 14px;width:14px}
.stability-summary{display:flex;gap:24px;flex-wrap:wrap;padding:12px 15px;border-bottom:1px solid var(--nvr-border);color:var(--nvr-muted);font-size:10px}.stability-summary b{color:var(--nvr-text);font-weight:600}.snapshot-time{padding:12px 2px 0;text-align:right;color:#5f6d7e;font-size:9px}
:deep(.el-table){--el-table-bg-color:var(--nvr-surface);--el-table-tr-bg-color:var(--nvr-surface);--el-table-header-bg-color:#111820;--el-table-row-hover-bg-color:var(--nvr-surface-2);--el-table-border-color:var(--nvr-border);--el-table-text-color:#aeb9c6;--el-table-header-text-color:#718095;background:transparent}:deep(.el-table th.el-table__cell){font-size:10px}:deep(.el-table td.el-table__cell){font-size:10px}
@media(max-width:1250px){.metrics{grid-template-columns:repeat(3,1fr)}.two-column{grid-template-columns:1fr}}
@media(max-width:720px){.health-v2{padding:14px}.metrics{grid-template-columns:repeat(2,1fr)}.reliability-grid{grid-template-columns:repeat(2,1fr)}.panel-head{align-items:flex-start;flex-direction:column;padding:12px 15px}.panel-actions{width:100%;justify-content:space-between}}
</style>
