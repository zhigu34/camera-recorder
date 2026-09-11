<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

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
  auto_record: boolean
  expected_recording: boolean
  state: string
  abnormal: boolean
  pid?: number | null
  started_at?: string | null
  offline_since?: string | null
  restart_count: number
  warning_count: number
  timestamp_warning_count: number
  network_warning_count: number
  last_error?: string | null
  recordings_24h: RecordingStats
}

interface HealthSnapshot {
  generated_at: string
  process_started_at: string
  uptime_seconds: number
  cameras: {
    total: number
    enabled: number
    recording: number
    reconnecting: number
    abnormal: number
  }
  recordings_24h: RecordingStats
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

const snapshot = ref<HealthSnapshot | null>(null)
const loading = ref(false)
const wsConnected = ref(false)
const reconnectCount = ref(0)
let socket: WebSocket | null = null
let reconnectTimer: number | null = null
let destroyed = false

const pendingUploads = computed(() => {
  const value = snapshot.value?.uploads
  if (!value) return 0
  return (value.pending || 0) + (value.uploading || 0) + (value.retry_wait || 0)
})

function formatDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds || 0))
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return `${days}天 ${hours}小时 ${minutes}分`
  if (hours) return `${hours}小时 ${minutes}分`
  return `${minutes}分 ${seconds % 60}秒`
}

function formatBytes(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(2)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function formatStartedAt(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function stateTagType(state: string, abnormal: boolean) {
  if (abnormal) return 'danger'
  if (state === 'RECORDING') return 'success'
  if (state === 'RECONNECTING' || state === 'STARTING') return 'warning'
  return 'info'
}

function storageTagType() {
  if (snapshot.value?.storage.state === 'critical') return 'danger'
  if (snapshot.value?.storage.state === 'warning') return 'warning'
  return 'success'
}

async function loadSnapshot() {
  loading.value = true
  try {
    const { data } = await axios.get<HealthSnapshot>('/api/health/summary')
    snapshot.value = data
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '健康状态加载失败')
  } finally {
    loading.value = false
  }
}

function scheduleReconnect() {
  if (destroyed || reconnectTimer !== null) return
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    reconnectCount.value += 1
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

  socket.onopen = () => {
    wsConnected.value = true
    reconnectCount.value = 0
  }

  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data)
      if (message.type === 'health.snapshot' && message.data) {
        snapshot.value = message.data as HealthSnapshot
      }
    } catch {
      // Ignore malformed messages. The next two-second snapshot will replace it.
    }
  }

  socket.onerror = () => {
    wsConnected.value = false
  }

  socket.onclose = () => {
    wsConnected.value = false
    socket = null
    scheduleReconnect()
  }
}

function goBack() {
  window.location.href = '/'
}

onMounted(async () => {
  await loadSnapshot()
  connectWebSocket()
})

onBeforeUnmount(() => {
  destroyed = true
  if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
})
</script>

<template>
  <div class="health-page" v-loading="loading && !snapshot">
    <div class="page-head">
      <div>
        <div class="title-row">
          <h2>系统健康</h2>
          <el-tag :type="wsConnected ? 'success' : 'warning'">
            {{ wsConnected ? '实时连接' : '正在重连' }}
          </el-tag>
        </div>
        <p>V0.7 · Recorder / 录像片段 / 上传 / 磁盘实时运行状态</p>
      </div>
      <div class="head-actions">
        <el-button @click="loadSnapshot">立即刷新</el-button>
        <el-button @click="goBack">返回主界面</el-button>
      </div>
    </div>

    <template v-if="snapshot">
      <el-row :gutter="14">
        <el-col :xs="12" :sm="8" :md="4">
          <el-card shadow="never"><div class="metric">{{ formatDuration(snapshot.uptime_seconds) }}</div><div class="metric-label">服务运行时间</div></el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <el-card shadow="never"><div class="metric">{{ snapshot.cameras.recording }} / {{ snapshot.cameras.total }}</div><div class="metric-label">录像中</div></el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <el-card shadow="never"><div class="metric" :class="{ danger: snapshot.cameras.abnormal > 0 }">{{ snapshot.cameras.abnormal }}</div><div class="metric-label">异常摄像头</div></el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <el-card shadow="never"><div class="metric">{{ snapshot.recordings_24h.segments }}</div><div class="metric-label">24h 录像片段</div></el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <el-card shadow="never"><div class="metric" :class="{ danger: snapshot.recordings_24h.unhealthy_segments > 0 }">{{ snapshot.recordings_24h.unhealthy_segments }}</div><div class="metric-label">24h 异常片段</div></el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <el-card shadow="never"><div class="metric">{{ pendingUploads }}</div><div class="metric-label">待处理上传</div></el-card>
        </el-col>
      </el-row>

      <el-row :gutter="14" class="section-gap">
        <el-col :xs="24" :md="12">
          <el-card shadow="never">
            <template #header><strong>24 小时录像健康</strong></template>
            <div class="stats-grid">
              <div><span>总片段</span><strong>{{ snapshot.recordings_24h.segments }}</strong></div>
              <div><span>异常片段</span><strong>{{ snapshot.recordings_24h.unhealthy_segments }}</strong></div>
              <div><span>失败片段</span><strong>{{ snapshot.recordings_24h.failed_segments }}</strong></div>
              <div><span>全部警告</span><strong>{{ snapshot.recordings_24h.warning_count }}</strong></div>
              <div><span>时间戳警告</span><strong>{{ snapshot.recordings_24h.timestamp_warning_count }}</strong></div>
              <div><span>网络警告</span><strong>{{ snapshot.recordings_24h.network_warning_count }}</strong></div>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <strong>磁盘</strong>
                <el-tag :type="storageTagType()">{{ snapshot.storage.state }}</el-tag>
              </div>
            </template>
            <el-progress :percentage="snapshot.storage.used_percent" :stroke-width="18" />
            <div class="disk-detail">
              <span>已用 {{ formatBytes(snapshot.storage.used_bytes) }}</span>
              <span>剩余 {{ formatBytes(snapshot.storage.free_bytes) }}</span>
              <span>总计 {{ formatBytes(snapshot.storage.total_bytes) }}</span>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-card class="section-gap" shadow="never">
        <template #header>
          <div class="card-head">
            <strong>摄像头运行健康</strong>
            <span class="muted">实时计数来自当前 Recorder 进程；24h 数据来自已完成录像片段</span>
          </div>
        </template>

        <el-table :data="snapshot.camera_health" stripe empty-text="暂无摄像头">
          <el-table-column prop="name" label="摄像头" min-width="150" fixed="left" />
          <el-table-column prop="ip" label="IP" width="145" />
          <el-table-column label="状态" width="125">
            <template #default="{ row }">
              <el-tag :type="stateTagType(row.state, row.abnormal)">{{ row.state }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="运行起点" width="190">
            <template #default="{ row }">{{ formatStartedAt(row.started_at) }}</template>
          </el-table-column>
          <el-table-column prop="restart_count" label="重连" width="75" sortable />
          <el-table-column prop="timestamp_warning_count" label="时间戳" width="85" sortable />
          <el-table-column prop="network_warning_count" label="网络" width="75" sortable />
          <el-table-column label="24h片段" width="90" sortable :sort-method="(a: CameraHealth, b: CameraHealth) => a.recordings_24h.segments - b.recordings_24h.segments">
            <template #default="{ row }">{{ row.recordings_24h.segments }}</template>
          </el-table-column>
          <el-table-column label="24h异常" width="90" sortable :sort-method="(a: CameraHealth, b: CameraHealth) => a.recordings_24h.unhealthy_segments - b.recordings_24h.unhealthy_segments">
            <template #default="{ row }">
              <span :class="{ danger: row.recordings_24h.unhealthy_segments > 0 }">{{ row.recordings_24h.unhealthy_segments }}</span>
            </template>
          </el-table-column>
          <el-table-column label="最后错误" min-width="300" show-overflow-tooltip>
            <template #default="{ row }">{{ row.last_error || '-' }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <div class="snapshot-time">最后快照：{{ formatStartedAt(snapshot.generated_at) }}</div>
    </template>
  </div>
</template>

<style scoped>
:global(body) {
  margin: 0;
  background: #f5f7fa;
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.health-page { max-width: 1500px; margin: 0 auto; padding: 28px 24px 60px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; margin-bottom: 18px; }
.title-row { display: flex; align-items: center; gap: 12px; }
h2 { margin: 0; }
p { margin: 8px 0 0; color: #909399; }
.head-actions { display: flex; gap: 8px; }
.metric { font-size: 24px; line-height: 1.25; font-weight: 700; color: #303133; min-height: 30px; }
.metric-label { margin-top: 8px; color: #909399; font-size: 13px; }
.danger { color: #f56c6c; font-weight: 700; }
.section-gap { margin-top: 14px; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.muted { color: #909399; font-size: 12px; font-weight: normal; }
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
.stats-grid div { display: flex; flex-direction: column; gap: 7px; }
.stats-grid span { color: #909399; font-size: 12px; }
.stats-grid strong { font-size: 24px; }
.disk-detail { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px 18px; margin-top: 18px; color: #606266; font-size: 13px; }
.snapshot-time { text-align: right; color: #909399; font-size: 12px; margin-top: 12px; }
@media (max-width: 760px) {
  .page-head { flex-direction: column; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
