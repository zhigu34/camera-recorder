<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import CameraHealthDrawer from './components/health/CameraHealthDrawer.vue'
import CameraReliabilityTable from './components/health/CameraReliabilityTable.vue'
import HealthAttentionList from './components/health/HealthAttentionList.vue'
import HealthOverviewStrip from './components/health/HealthOverviewStrip.vue'
import HealthServiceStrip from './components/health/HealthServiceStrip.vue'
import {
  type RecordingGapDiagnostic,
  type ReliabilityWindow,
  useHealthReliabilityStore,
} from './stores/healthReliability'
import { useRuntimeStore } from './stores/runtime'
import { wallClockSeconds } from './utils/playbackTimelineV3'

const RELIABILITY_REFRESH_MS = 60_000

const route = useRoute()
const router = useRouter()
const runtime = useRuntimeStore()
const reliability = useHealthReliabilityStore()
const { healthSnapshot: realtime, systemStatus: system, socketState } = storeToRefs(runtime)
const { report, windowHours, loading, error } = storeToRefs(reliability)

function positiveRouteId(value: unknown) {
  const raw = Array.isArray(value) ? value[0] : value
  const parsed = Number(raw || 0)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

const selectedCameraId = ref<number | null>(positiveRouteId(route.query.camera_id))
const drawerOpen = ref(false)
let refreshTimer: number | null = null

const selectedRealtime = computed(() =>
  realtime.value?.camera_health.find((item) => item.camera_id === selectedCameraId.value) ?? null,
)
const selectedReliability = computed(() =>
  report.value?.cameras.find((item) => item.camera_id === selectedCameraId.value) ?? null,
)
const realtimeStatusLabel = computed(() => socketState.value === 'connected' ? '实时连接' : '轮询补偿')
const reliabilityStatusLabel = computed(() => {
  if (loading.value && !report.value) return '历史可靠性加载中'
  if (error.value) return '历史可靠性暂不可用'
  return report.value ? `最近 ${windowHours.value} 小时` : '等待历史可靠性数据'
})

function selectCamera(cameraId: number) {
  selectedCameraId.value = cameraId
  drawerOpen.value = true
  const query = { ...route.query, camera_id: String(cameraId) }
  void router.replace({ query })
}

function syncDeepLinkedCamera() {
  const cameraId = positiveRouteId(route.query.camera_id)
  if (!cameraId) {
    if (route.query.camera_id === undefined) {
      selectedCameraId.value = null
      drawerOpen.value = false
    }
    return
  }
  selectedCameraId.value = cameraId
  const exists = Boolean(
    realtime.value?.camera_health.some((item) => item.camera_id === cameraId)
    || report.value?.cameras.some((item) => item.camera_id === cameraId),
  )
  if (exists) drawerOpen.value = true
}

async function setWindow(hours: ReliabilityWindow) {
  await reliability.setWindow(hours)
}

async function refreshAll() {
  await Promise.all([
    runtime.refreshHealth(),
    runtime.refreshSystem(),
    reliability.refresh(true),
  ])
}

function openCamera(cameraId: number) {
  void router.push({ path: '/cameras', query: { camera_id: String(cameraId) } })
}

function openEvents(cameraId: number) {
  void router.push({ path: '/events', query: { camera_id: String(cameraId) } })
}

function openPlayback(diagnostic: RecordingGapDiagnostic) {
  if (!selectedCameraId.value) return
  const seconds = wallClockSeconds(diagnostic.start_at)
  if (seconds === null) return
  void router.push({
    path: '/recordings/playback',
    query: {
      camera_id: String(selectedCameraId.value),
      date: diagnostic.start_at.slice(0, 10),
      wall_seconds: String(seconds),
    },
  })
}

function openOperations() {
  void router.push({ path: '/settings', query: { section: 'operations' } })
}

function openPlaybackDiagnostics() {
  void router.push({ path: '/recordings/manage', hash: '#playback-compatibility' })
}

watch([() => route.query.camera_id, selectedRealtime, selectedReliability], syncDeepLinkedCamera, { immediate: true })
watch(drawerOpen, (open) => {
  if (open || positiveRouteId(route.query.camera_id) === null) return
  const query = { ...route.query }
  delete query.camera_id
  void router.replace({ query })
})

onMounted(() => {
  void reliability.refresh().then(syncDeepLinkedCamera)
  refreshTimer = window.setInterval(() => {
    if (!document.hidden) void reliability.refresh(true)
  }, RELIABILITY_REFRESH_MS)
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
  refreshTimer = null
})
</script>

<template>
  <main class="health-center">
    <header class="health-header">
      <div>
        <span class="eyebrow">HEALTH CENTER</span>
        <h1>系统健康</h1>
        <p>先看哪里需要关注，再查看原因与证据。实时状态和历史可靠性分别计算。</p>
      </div>
      <div class="header-actions">
        <span class="feed-state"><i :class="socketState === 'connected' ? 'live' : 'fallback'"></i>{{ realtimeStatusLabel }}</span>
        <div class="window-switch" aria-label="可靠性时间范围">
          <button type="button" :class="{ active: windowHours === 24 }" @click="setWindow(24)">24h</button>
          <button type="button" :class="{ active: windowHours === 72 }" @click="setWindow(72)">72h</button>
        </div>
        <button type="button" class="refresh-button" :disabled="loading" @click="refreshAll">刷新</button>
      </div>
    </header>

    <HealthOverviewStrip :realtime="realtime" :reliability="report" />

    <div v-if="error" class="history-notice">
      <strong>{{ reliabilityStatusLabel }}</strong>
      <span>{{ error }}。实时状态仍保持可用，历史数据恢复后会自动刷新。</span>
    </div>

    <section class="attention-section" aria-label="需要关注">
      <HealthAttentionList
        :realtime-cameras="realtime?.camera_health || []"
        :historical-issues="report?.issues || []"
        @select="selectCamera"
      />
    </section>

    <section class="reliability-section" aria-label="摄像头可靠性">
      <CameraReliabilityTable
        :cameras="report?.cameras || []"
        @select="selectCamera"
      />
    </section>

    <HealthServiceStrip
      :realtime="realtime"
      :system="system"
      @operations="openOperations"
      @playback="openPlaybackDiagnostics"
    />

    <CameraHealthDrawer
      v-model="drawerOpen"
      :realtime="selectedRealtime"
      :reliability="selectedReliability"
      @playback="openPlayback"
      @camera="openCamera"
      @events="openEvents"
    />
  </main>
</template>

<style scoped>
.health-center{width:min(1500px,100%);margin:0 auto;padding:20px 24px 30px;box-sizing:border-box;color:var(--nvr-text)}.health-header{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:12px}.eyebrow{color:var(--nvr-subtle);font-size:8px;font-weight:800;letter-spacing:.17em}.health-header h1{margin:4px 0 4px;font-size:20px;font-weight:670;letter-spacing:-.02em}.health-header p{margin:0;color:var(--nvr-muted);font-size:10px}.header-actions{display:flex;align-items:center;gap:7px}.feed-state{display:flex;align-items:center;gap:5px;color:var(--nvr-muted);font-size:8px;white-space:nowrap}.feed-state i{width:6px;height:6px;border-radius:50%}.feed-state i.live{background:var(--nvr-green)}.feed-state i.fallback{background:var(--nvr-yellow)}.window-switch{display:flex;padding:2px;border:1px solid var(--nvr-border);border-radius:7px;background:var(--nvr-surface)}.window-switch button,.refresh-button{height:27px;border:0;border-radius:5px;background:transparent;color:var(--nvr-muted);font-size:9px;cursor:pointer}.window-switch button{min-width:40px}.window-switch button.active{background:var(--nvr-surface-2);color:var(--nvr-text)}.refresh-button{border:1px solid var(--nvr-border);padding:0 10px;background:var(--nvr-surface)}.refresh-button:disabled{opacity:.55;cursor:default}.history-notice{display:flex;align-items:center;gap:10px;margin-top:9px;padding:8px 10px;border:1px solid color-mix(in srgb,var(--nvr-yellow) 35%,var(--nvr-border));border-radius:7px;background:color-mix(in srgb,var(--nvr-yellow) 5%,var(--nvr-surface));font-size:9px}.history-notice strong{white-space:nowrap}.history-notice span{color:var(--nvr-muted)}.attention-section,.reliability-section{margin-top:10px}.attention-section,.reliability-section{display:block}.reliability-section+*{margin-top:10px}
@media(max-width:780px){.health-center{padding:15px}.health-header{align-items:flex-start;flex-direction:column}.header-actions{width:100%;flex-wrap:wrap}.refresh-button{margin-left:auto}.history-notice{align-items:flex-start;flex-direction:column}}
</style>
