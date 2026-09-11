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

interface CameraTrend {
  camera_id: number
  name: string
  ip: string
  monitored: boolean
  samples: number
  observed_minutes: number
  online_samples: number
  online_rate: number | null
  recording_segments: number
  complete_segments: number
  recording_completeness: number | null
}

interface TrendPoint {
  started_at: string
  expected_samples: number
  online_samples: number
  abnormal_samples: number
  online_rate: number | null
}

interface HealthTrends {
  generated_at: string
  hours: number
  bucket_minutes: number
  retention_days: number
  sample_interval_seconds: number
  overall: {
    monitored_cameras: number
    samples: number
    online_samples: number
    online_rate: number | null
    recording_segments: number
    complete_segments: number
    recording_completeness: number | null
  }
  cameras: CameraTrend[]
  timeline: TrendPoint[]
}

type StabilityVerdict = 'pass' | 'fail' | 'collecting' | 'ignored'

interface StabilityCamera {
  camera_id: number
  name: string
  ip: string
  monitored: boolean
  verdict: StabilityVerdict
  reasons: string[]
  sample_coverage: number
  observed_minutes: number
  online_rate: number | null
  recording_completeness: number | null
  recording_segments: number
  complete_segments: number
  ffmpeg_failures: number
  failure_streaks: number
  max_consecutive_failures: number
  outage_count: number
  total_offline_seconds: number
  longest_offline_seconds: number
  current_offline_seconds: number
  continuous_failure_active: boolean
}

interface StabilityReport {
  generated_at: string
  hours: number
  criteria: {
    min_sample_coverage: number
    min_online_rate: number
    min_recording_completeness: number
    max_longest_outage_seconds: number
    max_failure_streaks: number
    max_ffmpeg_failures_per_24h: number
    max_ffmpeg_failures: number
  }
  overall: {
    verdict: Exclude<StabilityVerdict, 'ignored'>
    monitored_cameras: number
    passed_cameras: number
    failed_cameras: number
    collecting_cameras: number
    online_rate: number | null
    recording_completeness: number | null
    ffmpeg_failures: number
    failure_streaks: number
    outage_count: number
    total_offline_seconds: number
    longest_offline_seconds: number
  }
  cameras: StabilityCamera[]
}

const snapshot = ref<HealthSnapshot | null>(null)
const trends = ref<HealthTrends | null>(null)
const stability = ref<StabilityReport | null>(null)
const stabilityWindow = ref(24)
const loading = ref(false)
const trendLoading = ref(false)
const stabilityLoading = ref(false)
const wsConnected = ref(false)
const reconnectCount = ref(0)
let socket: WebSocket | null = null
let reconnectTimer: number | null = null
let trendTimer: number | null = null
let destroyed = false

const pendingUploads = computed(() => {
  const value = snapshot.value?.uploads
  if (!value) return 0
  return (value.pending || 0) + (value.uploading || 0) + (value.retry_wait || 0)
})

const monitoredCameraTrends = computed(() =>
  (trends.value?.cameras || []).filter((item) => item.monitored),
)

const monitoredStabilityCameras = computed(() =>
  (stability.value?.cameras || []).filter((item) => item.monitored),
)

function formatDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds || 0))
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return `${days}天 ${hours}小时 ${minutes}分`
  if (hours) return `${hours}小时 ${minutes}分`
  if (minutes) return `${minutes}分 ${seconds % 60}秒`
  return `${seconds}秒`
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

function formatHour(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${String(date.getHours()).padStart(2, '0')}:00`
}

function formatRate(value: number | null | undefined) {
  return value === null || value === undefined ? '-' : `${value.toFixed(2)}%`
}

function rateType(value: number | null | undefined) {
  if (value === null || value === undefined) return 'info'
  if (value >= 99.9) return 'success'
  if (value >= 99) return 'warning'
  return 'danger'
}

function verdictType(value: StabilityVerdict) {
  if (value === 'pass') return 'success'
  if (value === 'fail') return 'danger'
  if (value === 'collecting') return 'warning'
  return 'info'
}

function verdictLabel(value: StabilityVerdict) {
  if (value === 'pass') return '通过'
  if (value === 'fail') return '未通过'
  if (value === 'collecting') return '采集中'
  return '未监控'
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

function sortSegments24h(a: CameraHealth, b: CameraHealth) {
  return a.recordings_24h.segments - b.recordings_24h.segments
}

function sortUnhealthy24h(a: CameraHealth, b: CameraHealth) {
  return a.recordings_24h.unhealthy_segments - b.recordings_24h.unhealthy_segments
}

function sortOnlineRate(a: CameraTrend, b: CameraTrend) {
  return (a.online_rate ?? -1) - (b.online_rate ?? -1)
}

function sortCompleteness(a: CameraTrend, b: CameraTrend) {
  return (a.recording_completeness ?? -1) - (b.recording_completeness ?? -1)
}

function sortStabilityCoverage(a: StabilityCamera, b: StabilityCamera) {
  return a.sample_coverage - b.sample_coverage
}

function sortStabilityOnline(a: StabilityCamera, b: StabilityCamera) {
  return (a.online_rate ?? -1) - (b.online_rate ?? -1)
}

function sortStabilityCompleteness(a: StabilityCamera, b: StabilityCamera) {
  return (a.recording_completeness ?? -1) - (b.recording_completeness ?? -1)
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

async function loadTrends(showError = true) {
  trendLoading.value = true
  try {
    const { data } = await axios.get<HealthTrends>('/api/health/trends', {
      params: { hours: 24, bucket_minutes: 60 },
    })
    trends.value = data
  } catch (error) {
    if (showError) {
      ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '健康趋势加载失败')
    }
  } finally {
    trendLoading.value = false
  }
}

async function loadStability(showError = true) {
  stabilityLoading.value = true
  try {
    const { data } = await axios.get<StabilityReport>('/api/health/stability', {
      params: { hours: stabilityWindow.value },
    })
    stability.value = data
  } catch (error) {
    if (showError) {
      ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '稳定性验收数据加载失败')
    }
  } finally {
    stabilityLoading.value = false
  }
}

function onStabilityWindowChange() {
  void loadStability()
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
  await Promise.all([loadSnapshot(), loadTrends(), loadStability()])
  connectWebSocket()
  trendTimer = window.setInterval(() => {
    void loadTrends(false)
    void loadStability(false)
  }, 60_000)
})

onBeforeUnmount(() => {
  destroyed = true
  if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
  if (trendTimer !== null) window.clearInterval(trendTimer)
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
        <p>V0.7 · 实时状态 + 24h 趋势 + 24h/72h 稳定性压测验收</p>
      </div>
      <div class="head-actions">
        <el-button @click="loadStability()" :loading="stabilityLoading">刷新验收</el-button>
        <el-button @click="loadTrends()" :loading="trendLoading">刷新趋势</el-button>
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

      <el-row v-if="trends" :gutter="14" class="section-gap">
        <el-col :xs="12" :sm="8" :md="6">
          <el-card shadow="never">
            <div class="metric"><el-tag size="large" :type="rateType(trends.overall.online_rate)">{{ formatRate(trends.overall.online_rate) }}</el-tag></div>
            <div class="metric-label">24h 在线率</div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6">
          <el-card shadow="never">
            <div class="metric"><el-tag size="large" :type="rateType(trends.overall.recording_completeness)">{{ formatRate(trends.overall.recording_completeness) }}</el-tag></div>
            <div class="metric-label">24h 录像完整率</div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6">
          <el-card shadow="never"><div class="metric">{{ trends.overall.monitored_cameras }}</div><div class="metric-label">自动录像监控摄像头</div></el-card>
        </el-col>
        <el-col :xs="12" :sm="8" :md="6">
          <el-card shadow="never"><div class="metric">{{ trends.overall.samples }}</div><div class="metric-label">24h 健康采样点</div></el-card>
        </el-col>
      </el-row>

      <el-card v-if="stability" class="section-gap" shadow="never" v-loading="stabilityLoading">
        <template #header>
          <div class="card-head">
            <div class="title-row compact">
              <strong>稳定性压测验收</strong>
              <el-tag size="large" :type="verdictType(stability.overall.verdict)">
                {{ verdictLabel(stability.overall.verdict) }}
              </el-tag>
            </div>
            <el-radio-group v-model="stabilityWindow" size="small" @change="onStabilityWindowChange">
              <el-radio-button :value="24">24 小时</el-radio-button>
              <el-radio-button :value="72">72 小时</el-radio-button>
            </el-radio-group>
          </div>
        </template>

        <div class="acceptance-grid">
          <div><span>通过摄像头</span><strong>{{ stability.overall.passed_cameras }} / {{ stability.overall.monitored_cameras }}</strong></div>
          <div><span>FFmpeg 异常</span><strong :class="{ danger: stability.overall.ffmpeg_failures > 0 }">{{ stability.overall.ffmpeg_failures }}</strong></div>
          <div><span>连续失败事件</span><strong :class="{ danger: stability.overall.failure_streaks > 0 }">{{ stability.overall.failure_streaks }}</strong></div>
          <div><span>断流次数</span><strong>{{ stability.overall.outage_count }}</strong></div>
          <div><span>最长单次断流</span><strong :class="{ danger: stability.overall.longest_offline_seconds > stability.criteria.max_longest_outage_seconds }">{{ formatDuration(stability.overall.longest_offline_seconds) }}</strong></div>
          <div><span>累计断流</span><strong>{{ formatDuration(stability.overall.total_offline_seconds) }}</strong></div>
        </div>

        <div class="criteria-note">
          验收线：采样覆盖率 ≥ {{ stability.criteria.min_sample_coverage }}%，在线率 ≥ {{ stability.criteria.min_online_rate }}%，录像完整率 ≥ {{ stability.criteria.min_recording_completeness }}%，最长单次断流 ≤ {{ stability.criteria.max_longest_outage_seconds }} 秒，连续失败事件 = 0，FFmpeg 异常 ≤ {{ stability.criteria.max_ffmpeg_failures }} 次。
        </div>

        <el-table :data="monitoredStabilityCameras" stripe empty-text="暂无自动录像摄像头" class="acceptance-table">
          <el-table-column prop="name" label="摄像头" min-width="150" fixed="left" />
          <el-table-column label="结果" width="95">
            <template #default="{ row }"><el-tag :type="verdictType(row.verdict)">{{ verdictLabel(row.verdict) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="采样覆盖" width="110" sortable :sort-method="sortStabilityCoverage">
            <template #default="{ row }">{{ formatRate(row.sample_coverage) }}</template>
          </el-table-column>
          <el-table-column label="在线率" width="110" sortable :sort-method="sortStabilityOnline">
            <template #default="{ row }"><el-tag :type="rateType(row.online_rate)">{{ formatRate(row.online_rate) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="录像完整率" width="125" sortable :sort-method="sortStabilityCompleteness">
            <template #default="{ row }"><el-tag :type="rateType(row.recording_completeness)">{{ formatRate(row.recording_completeness) }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="ffmpeg_failures" label="FFmpeg异常" width="105" sortable />
          <el-table-column prop="max_consecutive_failures" label="最大连续失败" width="115" sortable />
          <el-table-column prop="outage_count" label="断流次数" width="95" sortable />
          <el-table-column label="最长断流" width="115" sortable :sort-method="(a: StabilityCamera, b: StabilityCamera) => a.longest_offline_seconds - b.longest_offline_seconds">
            <template #default="{ row }">{{ formatDuration(row.longest_offline_seconds) }}</template>
          </el-table-column>
          <el-table-column label="当前离线" width="115">
            <template #default="{ row }"><span :class="{ danger: row.current_offline_seconds > 0 }">{{ row.current_offline_seconds > 0 ? formatDuration(row.current_offline_seconds) : '-' }}</span></template>
          </el-table-column>
          <el-table-column label="原因" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">{{ row.reasons.length ? row.reasons.join('；') : '-' }}</template>
          </el-table-column>
        </el-table>
      </el-card>

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

      <el-card v-if="trends" class="section-gap" shadow="never">
        <template #header>
          <div class="card-head">
            <strong>24 小时在线趋势</strong>
            <span class="muted">每分钟采样，按小时聚合；升级后需要逐步积累样本</span>
          </div>
        </template>
        <div v-if="trends.timeline.length" class="trend-strip">
          <div
            v-for="point in trends.timeline"
            :key="point.started_at"
            class="trend-column"
            :title="`${formatStartedAt(point.started_at)} · 在线率 ${formatRate(point.online_rate)} · 异常采样 ${point.abnormal_samples}`"
          >
            <div class="trend-well">
              <div class="trend-fill" :style="{ height: `${point.online_rate ?? 0}%` }" />
            </div>
            <span>{{ formatHour(point.started_at) }}</span>
          </div>
        </div>
        <el-empty v-else description="健康采样刚开始，约 1 分钟后会出现趋势数据" :image-size="70" />
      </el-card>

      <el-card v-if="trends" class="section-gap" shadow="never">
        <template #header>
          <div class="card-head">
            <strong>摄像头 24h 稳定性</strong>
            <span class="muted">录像完整率 = 健康且 ffprobe 通过的完整片段 / 已完成片段</span>
          </div>
        </template>
        <el-table :data="monitoredCameraTrends" stripe empty-text="暂无自动录像摄像头">
          <el-table-column prop="name" label="摄像头" min-width="160" fixed="left" />
          <el-table-column prop="ip" label="IP" width="145" />
          <el-table-column label="在线率" width="120" sortable :sort-method="sortOnlineRate">
            <template #default="{ row }"><el-tag :type="rateType(row.online_rate)">{{ formatRate(row.online_rate) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="录像完整率" width="130" sortable :sort-method="sortCompleteness">
            <template #default="{ row }"><el-tag :type="rateType(row.recording_completeness)">{{ formatRate(row.recording_completeness) }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="observed_minutes" label="已采样分钟" width="110" sortable />
          <el-table-column prop="recording_segments" label="录像片段" width="95" sortable />
          <el-table-column prop="complete_segments" label="完整片段" width="95" sortable />
        </el-table>
      </el-card>

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
          <el-table-column label="24h片段" width="90" sortable :sort-method="sortSegments24h">
            <template #default="{ row }">{{ row.recordings_24h.segments }}</template>
          </el-table-column>
          <el-table-column label="24h异常" width="90" sortable :sort-method="sortUnhealthy24h">
            <template #default="{ row }">
              <span :class="{ danger: row.recordings_24h.unhealthy_segments > 0 }">{{ row.recordings_24h.unhealthy_segments }}</span>
            </template>
          </el-table-column>
          <el-table-column label="最后错误" min-width="300" show-overflow-tooltip>
            <template #default="{ row }">{{ row.last_error || '-' }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <div class="snapshot-time">
        实时快照：{{ formatStartedAt(snapshot.generated_at) }}
        <template v-if="trends"> · 趋势统计：{{ formatStartedAt(trends.generated_at) }}</template>
        <template v-if="stability"> · 验收统计：{{ formatStartedAt(stability.generated_at) }}</template>
      </div>
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
.title-row.compact { gap: 10px; }
h2 { margin: 0; }
p { margin: 8px 0 0; color: #909399; }
.head-actions { display: flex; flex-wrap: wrap; gap: 8px; }
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
.acceptance-grid { display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); gap: 14px; }
.acceptance-grid div { border: 1px solid #ebeef5; border-radius: 6px; padding: 14px; display: flex; flex-direction: column; gap: 8px; }
.acceptance-grid span { color: #909399; font-size: 12px; }
.acceptance-grid strong { font-size: 20px; }
.criteria-note { margin-top: 14px; padding: 10px 12px; background: #f5f7fa; border-radius: 6px; color: #606266; font-size: 12px; line-height: 1.7; }
.acceptance-table { margin-top: 14px; }
.disk-detail { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px 18px; margin-top: 18px; color: #606266; font-size: 13px; }
.trend-strip { display: flex; align-items: flex-end; gap: 8px; overflow-x: auto; padding: 4px 2px 6px; min-height: 155px; }
.trend-column { flex: 1 0 42px; min-width: 42px; display: flex; flex-direction: column; align-items: center; gap: 7px; }
.trend-column span { color: #909399; font-size: 10px; white-space: nowrap; }
.trend-well { width: 22px; height: 112px; background: #f0f2f5; border-radius: 4px; overflow: hidden; display: flex; align-items: flex-end; }
.trend-fill { width: 100%; min-height: 2px; background: #67c23a; transition: height 0.2s ease; }
.snapshot-time { text-align: right; color: #909399; font-size: 12px; margin-top: 12px; }
@media (max-width: 1180px) {
  .acceptance-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 760px) {
  .page-head { flex-direction: column; }
  .card-head { align-items: flex-start; flex-direction: column; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .acceptance-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
