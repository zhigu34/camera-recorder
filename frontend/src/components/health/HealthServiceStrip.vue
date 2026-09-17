<script setup lang="ts">
import axios from 'axios'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import type { RealtimeHealthSnapshot, SystemStatus } from '../../stores/runtime'

defineProps<{
  realtime: RealtimeHealthSnapshot | null
  system: SystemStatus | null
}>()
const emit = defineEmits<{
  operations: []
  playback: []
}>()

interface LatencySummary {
  p95_ms: number | null
}

interface PlaybackMetrics {
  client: {
    events: {
      first_frame: LatencySummary & { count: number }
      startup_error: { count: number }
    }
    compatibility: Array<{ success_rate: number | null }>
  }
}

const PLAYBACK_REFRESH_MS = 60_000
const playbackMetrics = ref<PlaybackMetrics | null>(null)
let playbackTimer: number | null = null

const startupAttempts = computed(() => {
  if (!playbackMetrics.value) return 0
  return playbackMetrics.value.client.events.first_frame.count + playbackMetrics.value.client.events.startup_error.count
})
const startupSuccessRate = computed(() => {
  if (!playbackMetrics.value || startupAttempts.value === 0) return null
  return playbackMetrics.value.client.events.first_frame.count / startupAttempts.value * 100
})
const compatibilityProblems = computed(() =>
  (playbackMetrics.value?.client.compatibility || []).filter((item) => (item.success_rate ?? 100) < 98).length,
)
const playbackHealthy = computed(() => {
  if (startupSuccessRate.value === null) return null
  return startupSuccessRate.value >= 98 && compatibilityProblems.value === 0
})

function statusClass(ok: boolean | null) {
  if (ok === null) return 'unknown'
  return ok ? 'healthy' : 'attention'
}

function formatRate(value: number | null) {
  return value === null ? '-' : `${value.toFixed(1)}%`
}

function formatMs(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`
  return `${Math.round(value)} ms`
}

function formatBytes(value: number | null | undefined) {
  const amount = Math.max(0, Number(value || 0))
  if (amount >= 1024 ** 4) return `${(amount / 1024 ** 4).toFixed(2)} TB`
  if (amount >= 1024 ** 3) return `${(amount / 1024 ** 3).toFixed(1)} GB`
  if (amount >= 1024 ** 2) return `${(amount / 1024 ** 2).toFixed(0)} MB`
  return `${Math.round(amount / 1024)} KB`
}

async function loadPlaybackMetrics() {
  try {
    playbackMetrics.value = (await axios.get<PlaybackMetrics>('/api/playback/metrics')).data
  } catch {
    // Health remains usable when playback metrics are temporarily unavailable.
  }
}

onMounted(() => {
  void loadPlaybackMetrics()
  playbackTimer = window.setInterval(() => void loadPlaybackMetrics(), PLAYBACK_REFRESH_MS)
})

onBeforeUnmount(() => {
  if (playbackTimer !== null) window.clearInterval(playbackTimer)
  playbackTimer = null
})
</script>

<template>
  <section class="service-strip">
    <header><div><span>SERVICES</span><h2>服务状态</h2></div><small>这里只保留摘要，详细运维与回放诊断在对应工作区查看</small></header>
    <div class="services">
      <button type="button" @click="emit('operations')">
        <i :class="statusClass(realtime ? realtime.storage.state !== 'critical' : null)"></i>
        <span><strong>磁盘空间</strong><small>{{ realtime ? `${realtime.storage.used_percent}% 已使用 · 本地录像 ${formatBytes(realtime.storage.local_recordings_bytes)}` : '等待状态' }}</small></span><b>›</b>
      </button>
      <button type="button" @click="emit('operations')">
        <i :class="statusClass(realtime ? (!realtime.upload.enabled || realtime.upload.configured) : null)"></i>
        <span><strong>OpenList / WebDAV</strong><small>{{ realtime?.upload.active ? '归档服务可用' : realtime?.upload.enabled ? '等待完整配置' : '未启用' }}</small></span><b>›</b>
      </button>
      <button type="button" @click="emit('operations')">
        <i :class="statusClass(realtime?.connectivity_monitor?.running ?? null)"></i>
        <span><strong>连接监控</strong><small>{{ realtime?.connectivity_monitor?.last_error || (realtime?.connectivity_monitor?.running ? '持续运行中' : '未运行') }}</small></span><b>›</b>
      </button>
      <button type="button" @click="emit('operations')">
        <i :class="statusClass(system?.ffmpeg ? system.ffmpeg.setts_available !== false : null)"></i>
        <span><strong>FFmpeg / setts</strong><small>{{ system?.ffmpeg?.ffmpeg_version || '检测运行环境' }}</small></span><b>›</b>
      </button>
      <button type="button" @click="emit('playback')">
        <i :class="statusClass(playbackHealthy)"></i>
        <span>
          <strong>Web 回放</strong>
          <small v-if="playbackMetrics">首帧成功率 {{ formatRate(startupSuccessRate) }} · 首帧 P95 {{ formatMs(playbackMetrics.client.events.first_frame.p95_ms) }} · 启动失败 {{ playbackMetrics.client.events.startup_error.count }} · 兼容异常组 {{ compatibilityProblems }}</small>
          <small v-else>回放指标暂不可用</small>
        </span>
        <b>›</b>
      </button>
    </div>
  </section>
</template>

<style scoped>
.service-strip{border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface);overflow:hidden}.service-strip>header{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;padding:11px 14px;border-bottom:1px solid var(--nvr-border)}header span{color:var(--nvr-subtle);font-size:8px;font-weight:800;letter-spacing:.15em}h2{margin:3px 0 0;font-size:12px;font-weight:650}header small{color:var(--nvr-subtle);font-size:8px}.services{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:var(--nvr-border)}.services button{display:grid;grid-template-columns:8px minmax(0,1fr) 10px;align-items:center;gap:8px;min-height:60px;padding:9px 11px;border:0;background:var(--nvr-surface);color:inherit;text-align:left;cursor:pointer}.services button:hover{background:var(--nvr-hover)}.services i{width:6px;height:6px;border-radius:50%}.services i.healthy{background:var(--nvr-green)}.services i.attention{background:var(--nvr-yellow)}.services i.unknown{background:#627084}.services span{display:flex;min-width:0;flex-direction:column;gap:3px}.services strong{font-size:9px;font-weight:600}.services small{overflow:hidden;color:var(--nvr-subtle);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.services b{color:var(--nvr-subtle);font-size:12px}
@media(max-width:1000px){.services{grid-template-columns:repeat(2,minmax(0,1fr))}.services button:last-child{grid-column:1/-1}}
@media(max-width:560px){.service-strip>header{align-items:flex-start;flex-direction:column}.services{grid-template-columns:1fr}.services button:last-child{grid-column:auto}}
</style>