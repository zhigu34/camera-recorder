<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'

interface LatencySummary {
  samples: number
  avg_ms: number | null
  p95_ms: number | null
  max_ms: number | null
}

interface CompatibilityRow {
  browser: string
  browser_version: string
  platform: string
  codec: string
  playback_mode: string
  source_kind: string
  attempts: number
  successful_starts: number
  startup_errors: number
  success_rate: number | null
  first_frame: LatencySummary
  frame_signals: Record<string, number>
  hevc_hints: Record<string, number>
}

interface PlaybackMetrics {
  prefetch: {
    scheduled: number
    success: number
    direct_hits: number
    failures: number
    active_tasks: number
    cached_direct_links: number
    probe_latency: LatencySummary
  }
  backend_response: {
    stream: LatencySummary
    cloud: LatencySummary
    proxy: LatencySummary
  }
  client: {
    sample_count: number
    events: {
      decode_ready: LatencySummary & { count: number }
      first_frame: LatencySummary & { count: number }
      startup_error: { count: number }
      playback_error: { count: number }
    }
    compatibility: CompatibilityRow[]
  }
}

const metrics = ref<PlaybackMetrics | null>(null)
const loading = ref(false)
let timer: number | null = null

const startupAttempts = computed(() => {
  if (!metrics.value) return 0
  return metrics.value.client.events.first_frame.count + metrics.value.client.events.startup_error.count
})
const startupSuccessRate = computed(() => {
  const attempts = startupAttempts.value
  if (!attempts || !metrics.value) return null
  return metrics.value.client.events.first_frame.count / attempts * 100
})

function formatMs(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`
  return `${Math.round(value)} ms`
}

function formatRate(value: number | null | undefined) {
  return value === null || value === undefined ? '-' : `${value.toFixed(1)}%`
}

function rateType(value: number | null | undefined) {
  if (value === null || value === undefined) return 'info'
  if (value >= 98) return 'success'
  if (value >= 90) return 'warning'
  return 'danger'
}

function sourceLabel(value: string) {
  if (value === 'openlist_stream') return 'OpenList'
  if (value === 'cloud_cache') return '云端缓存'
  if (value === 'local') return '本地'
  return value
}

function modeLabel(value: string) {
  if (value === 'proxy-live') return '边转边播'
  if (value === 'proxy') return 'Proxy'
  if (value === 'original') return '原片'
  return value
}

function browserLabel(row: CompatibilityRow) {
  return row.browser_version && row.browser_version !== 'unknown'
    ? `${row.browser} ${row.browser_version}`
    : row.browser
}

function hintsLabel(value: Record<string, number>) {
  const entries = Object.entries(value)
  if (!entries.length) return '-'
  return entries.map(([key, count]) => `${key}:${count}`).join(' / ')
}

async function loadMetrics() {
  loading.value = true
  try {
    metrics.value = (await axios.get<PlaybackMetrics>('/api/playback/metrics')).data
  } catch {
    // Health page remains usable even if playback metrics are temporarily unavailable.
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadMetrics()
  timer = window.setInterval(() => void loadMetrics(), 30_000)
})

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <div class="playback-health" v-loading="loading && !metrics">
    <el-card shadow="never">
      <template #header>
        <div class="panel-head">
          <div>
            <strong>Web 回放质量 / 浏览器兼容性</strong>
            <div class="subtitle">真实播放器事件 · 内存统计 · 服务重启后清空</div>
          </div>
          <el-button size="small" :loading="loading" @click="loadMetrics">刷新</el-button>
        </div>
      </template>

      <template v-if="metrics">
        <el-row :gutter="12" class="metric-row">
          <el-col :xs="12" :sm="8" :md="4"><div class="metric-box"><strong>{{ startupAttempts }}</strong><span>播放启动样本</span></div></el-col>
          <el-col :xs="12" :sm="8" :md="4"><div class="metric-box"><strong>{{ formatRate(startupSuccessRate) }}</strong><span>首帧成功率</span></div></el-col>
          <el-col :xs="12" :sm="8" :md="4"><div class="metric-box"><strong>{{ formatMs(metrics.client.events.first_frame.avg_ms) }}</strong><span>真实首帧平均</span></div></el-col>
          <el-col :xs="12" :sm="8" :md="4"><div class="metric-box"><strong>{{ formatMs(metrics.client.events.first_frame.p95_ms) }}</strong><span>真实首帧 P95</span></div></el-col>
          <el-col :xs="12" :sm="8" :md="4"><div class="metric-box"><strong>{{ metrics.client.events.startup_error.count }}</strong><span>启动解码错误</span></div></el-col>
          <el-col :xs="12" :sm="8" :md="4"><div class="metric-box"><strong>{{ metrics.prefetch.direct_hits }}</strong><span>云端预热命中</span></div></el-col>
        </el-row>

        <div class="backend-strip">
          <span>OpenList 预热探测 P95 <b>{{ formatMs(metrics.prefetch.probe_latency.p95_ms) }}</b></span>
          <span>本地/原片响应 P95 <b>{{ formatMs(metrics.backend_response.stream.p95_ms) }}</b></span>
          <span>云端响应 P95 <b>{{ formatMs(metrics.backend_response.cloud.p95_ms) }}</b></span>
          <span>Proxy 响应 P95 <b>{{ formatMs(metrics.backend_response.proxy.p95_ms) }}</b></span>
          <span>预热失败 <b>{{ metrics.prefetch.failures }}</b></span>
        </div>

        <el-table :data="metrics.client.compatibility" size="small" empty-text="还没有真实浏览器回放样本">
          <el-table-column label="浏览器" width="110"><template #default="{ row }">{{ browserLabel(row) }}</template></el-table-column>
          <el-table-column prop="platform" label="平台" width="90" />
          <el-table-column prop="codec" label="编码" width="80" />
          <el-table-column label="模式" width="100"><template #default="{ row }">{{ modeLabel(row.playback_mode) }}</template></el-table-column>
          <el-table-column label="来源" width="105"><template #default="{ row }">{{ sourceLabel(row.source_kind) }}</template></el-table-column>
          <el-table-column prop="attempts" label="启动" width="70" />
          <el-table-column label="成功率" width="90"><template #default="{ row }"><el-tag :type="rateType(row.success_rate)">{{ formatRate(row.success_rate) }}</el-tag></template></el-table-column>
          <el-table-column label="首帧平均" width="100"><template #default="{ row }">{{ formatMs(row.first_frame.avg_ms) }}</template></el-table-column>
          <el-table-column label="首帧 P95" width="100"><template #default="{ row }">{{ formatMs(row.first_frame.p95_ms) }}</template></el-table-column>
          <el-table-column label="HEVC 声明" min-width="150"><template #default="{ row }">{{ hintsLabel(row.hevc_hints) }}</template></el-table-column>
        </el-table>
      </template>
      <el-empty v-else-if="!loading" description="回放质量指标暂不可用" />
    </el-card>
  </div>
</template>

<style scoped>
.playback-health{max-width:1500px;margin:16px auto 24px;padding:0 24px;box-sizing:border-box}.panel-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.subtitle{margin-top:4px;color:#909399;font-size:12px}.metric-row{margin-bottom:14px}.metric-box{min-height:72px;border:1px solid #ebeef5;border-radius:7px;background:#fafafa;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:5px}.metric-box strong{font-size:21px;color:#303133}.metric-box span{font-size:12px;color:#909399}.backend-strip{display:flex;flex-wrap:wrap;gap:8px 18px;padding:10px 12px;margin-bottom:14px;background:#f5f7fa;border-radius:6px;color:#606266;font-size:12px}.backend-strip b{color:#303133}@media(max-width:720px){.playback-health{padding:0 14px}.panel-head{align-items:flex-start}}
</style>
