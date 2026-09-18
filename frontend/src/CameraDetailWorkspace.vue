<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'

import type { EventDetectionOverview } from './event-detection/types'
import { eventDetectionRoute } from './navigation'

const props = defineProps<{ cameraId: number }>()

const router = useRouter()
const detectionOverview = ref<EventDetectionOverview | null>(null)
const detectionLoading = ref(false)
const detectionError = ref('')
let requestId = 0

const motionSource = computed(() =>
  detectionOverview.value?.sources.find((source) => source.id === 'local.motion') || null,
)
const motionEnabled = computed(() =>
  detectionOverview.value?.enabled_source_ids.includes('local.motion') ?? false,
)
const motionRuntimeLabel = computed(() => {
  if (detectionLoading.value) return '读取中'
  if (detectionError.value) return '状态不可用'
  if (!motionSource.value) return '不可用'
  if (motionSource.value.status === 'error') return '检测异常'
  if (motionSource.value.status !== 'available') return '不可用'
  if (!motionEnabled.value) return '已关闭'
  const state = motionSource.value.runtime_state
  if (state === 'warming_up') return '背景学习中'
  if (state === 'stabilizing') return '画面稳定中'
  if (state === 'running') return '检测中'
  if (state === 'starting') return '启动中'
  if (state === 'reconnecting') return '正在重连'
  if (state === 'error') return '检测异常'
  if (state === 'stopped') return '等待启动'
  return '已启用'
})
const motionStatusSummary = computed(() => {
  if (detectionError.value) return detectionError.value
  if (!motionSource.value) return '当前摄像头没有可用的本地移动检测来源'
  if (motionSource.value.reason) return motionSource.value.reason
  return motionEnabled.value ? '配置已启用' : '当前未启用'
})

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

async function loadDetectionSummary() {
  const cameraId = props.cameraId
  const current = ++requestId
  detectionOverview.value = null
  detectionError.value = ''
  detectionLoading.value = true
  try {
    const response = await axios.get<EventDetectionOverview>(
      `/api/cameras/${cameraId}/event-detection`,
    )
    if (current === requestId) detectionOverview.value = response.data
  } catch {
    if (current === requestId) detectionError.value = '事件检测状态读取失败'
  } finally {
    if (current === requestId) detectionLoading.value = false
  }
}

function openPlayback() {
  void router.push({
    path: '/recordings/playback',
    query: { camera_id: String(props.cameraId), date: todayString() },
  })
}

function openRecordings() {
  void router.push({
    path: '/recordings/manage',
    query: { camera_id: String(props.cameraId), date: todayString() },
  })
}

function openEventDetection() {
  void router.push(eventDetectionRoute(props.cameraId))
}

watch(() => props.cameraId, () => void loadDetectionSummary(), { immediate: true })
onBeforeUnmount(() => { requestId += 1 })
</script>

<template>
  <div class="camera-detail-workspace">
    <section class="camera-drawer-shortcuts" aria-label="设备工作区快捷入口">
      <div class="camera-drawer-shortcut-copy">
        <strong>设备工作区</strong>
        <span>快速进入当前摄像头的历史回放或原始录像管理。</span>
      </div>
      <div class="camera-drawer-shortcut-actions">
        <button type="button" @click="openPlayback">
          <strong>回放</strong>
          <span>时间轴与事件</span>
        </button>
        <button type="button" @click="openRecordings">
          <strong>录像管理</strong>
          <span>片段与归档</span>
        </button>
      </div>
    </section>

    <section class="event-detection-portal-section" aria-label="事件检测">
      <div class="event-detection-portal-copy">
        <span class="portal-eyebrow">事件检测</span>
        <strong>本地移动检测</strong>
        <small>这里只显示当前检测状态；灵敏度、事件策略与检测区域统一在事件检测工作区配置。</small>
      </div>
      <div class="event-detection-portal-status">
        <span class="portal-status-pill" :class="{ active: motionEnabled, error: detectionError }">{{ motionRuntimeLabel }}</span>
        <small>{{ motionStatusSummary }}</small>
        <el-button text type="primary" :disabled="detectionLoading" @click="openEventDetection">前往配置</el-button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.camera-detail-workspace{order:1;display:grid;gap:10px;min-width:0}.event-detection-portal-section{min-width:0;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 15px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.event-detection-portal-copy{min-width:0;display:flex;flex-direction:column;gap:4px}.event-detection-portal-copy .portal-eyebrow{color:var(--nvr-blue);font-size:9px;font-weight:650;letter-spacing:.08em}.event-detection-portal-copy strong{color:var(--nvr-text);font-size:12px;font-weight:650}.event-detection-portal-copy small,.event-detection-portal-status small{color:var(--nvr-muted);font-size:10px;line-height:1.45}.event-detection-portal-status{flex:0 0 auto;display:flex;align-items:center;gap:10px}.portal-status-pill{padding:4px 8px;border:1px solid var(--nvr-border);border-radius:999px;color:var(--nvr-muted);background:var(--nvr-surface-2);font-size:10px;white-space:nowrap}.portal-status-pill.active{color:var(--nvr-green);border-color:color-mix(in srgb,var(--nvr-green) 30%,var(--nvr-border))}.portal-status-pill.error{color:var(--nvr-red);border-color:color-mix(in srgb,var(--nvr-red) 30%,var(--nvr-border))}
@media(max-width:720px){.event-detection-portal-section,.event-detection-portal-status{align-items:flex-start;flex-direction:column}}
</style>
