<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { useRoute, useRouter } from 'vue-router'
import BatchCamerasView from './BatchCamerasView.vue'
import CamerasView from './CamerasView.vue'
import type { EventSourceRead } from './event-detection/types'
import { eventDetectionRoute } from './navigation'
import { cameraIdFromRouteQuery } from './utils/cameraMotionPortal'

const emit = defineEmits<{
  (event: 'open-preview'): void
}>()

const route = useRoute()
const router = useRouter()
const batchVisible = ref(false)
const cameraViewKey = ref(0)
const motionPortalReady = ref(false)
const selectedCameraId = computed(() => cameraIdFromRouteQuery(route.query.camera_id))
const detectionSource = ref<EventSourceRead | null>(null)
const detectionLoading = ref(false)
const detectionError = ref('')
let portalObserver: MutationObserver | null = null
let detectionRequestId = 0

const motionEnabled = computed(() => detectionSource.value?.config.enabled === true)
const motionRuntimeLabel = computed(() => {
  if (detectionLoading.value) return '读取中'
  if (detectionError.value) return '状态不可用'
  if (!detectionSource.value) return '未读取'
  if (!motionEnabled.value) return '未启用'
  const state = detectionSource.value.descriptor.runtime_state
  if (state === 'warming_up') return '背景学习中'
  if (state === 'stabilizing') return '画面稳定中'
  if (state === 'running') return '检测中'
  if (state === 'starting') return '启动中'
  if (state === 'reconnecting') return '正在重连'
  if (state === 'error') return '检测异常'
  if (state === 'stopped') return '等待启动'
  return '已启用'
})
const motionZoneSummary = computed(() => {
  if (!detectionSource.value) return '区域状态未知'
  const enabledZones = detectionSource.value.zones.filter((zone) => zone.enabled).length
  return enabledZones ? `${enabledZones} 个启用区域` : '检测整个画面'
})

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function refreshMotionPortalTarget() {
  if (!selectedCameraId.value) {
    motionPortalReady.value = false
    return
  }
  motionPortalReady.value = Boolean(document.querySelector('.camera-detail-drawer .drawer-body-v2'))
}

async function loadDetectionSummary() {
  const cameraId = selectedCameraId.value
  const requestId = ++detectionRequestId
  detectionSource.value = null
  detectionError.value = ''
  if (!cameraId) {
    detectionLoading.value = false
    return
  }
  detectionLoading.value = true
  try {
    const response = await axios.get<EventSourceRead>(
      `/api/cameras/${cameraId}/event-detection/sources/local.motion`,
    )
    if (requestId === detectionRequestId) detectionSource.value = response.data
  } catch {
    if (requestId === detectionRequestId) detectionError.value = '移动检测状态读取失败'
  } finally {
    if (requestId === detectionRequestId) detectionLoading.value = false
  }
}

watch(() => route.path, (path) => {
  batchVisible.value = path === '/cameras/batch'
}, { immediate: true })

watch(() => route.query.camera_id, async () => {
  motionPortalReady.value = false
  await nextTick()
  refreshMotionPortalTarget()
  void loadDetectionSummary()
}, { immediate: true })

function openBatch() {
  batchVisible.value = true
  if (route.path !== '/cameras/batch') void router.push('/cameras/batch')
}
function closeBatch() {
  batchVisible.value = false
  if (route.path === '/cameras/batch') void router.replace('/cameras')
}
function onBatchCompleted() {
  cameraViewKey.value += 1
}
function openCameraPlayback() {
  if (!selectedCameraId.value) return
  void router.push({
    path: '/recordings/playback',
    query: { camera_id: String(selectedCameraId.value), date: todayString() },
  })
}
function openCameraRecordings() {
  if (!selectedCameraId.value) return
  void router.push({
    path: '/recordings/manage',
    query: { camera_id: String(selectedCameraId.value), date: todayString() },
  })
}
function openEventDetection() {
  if (!selectedCameraId.value) return
  void router.push(eventDetectionRoute(selectedCameraId.value))
}

onMounted(() => {
  portalObserver = new MutationObserver(refreshMotionPortalTarget)
  portalObserver.observe(document.body, { childList: true, subtree: true })
  refreshMotionPortalTarget()
})

onBeforeUnmount(() => {
  portalObserver?.disconnect()
  portalObserver = null
  detectionRequestId += 1
})
</script>

<template>
  <CamerasView
    :key="cameraViewKey"
    @open-batch="openBatch"
    @open-preview="emit('open-preview')"
  />

  <Teleport v-if="selectedCameraId && motionPortalReady" to=".camera-detail-drawer .drawer-body-v2">
    <section class="camera-drawer-shortcuts" aria-label="设备工作区快捷入口">
      <div class="camera-drawer-shortcut-copy">
        <strong>设备工作区</strong>
        <span>快速进入当前摄像头的历史回放或原始录像管理。</span>
      </div>
      <div class="camera-drawer-shortcut-actions">
        <button type="button" @click="openCameraPlayback">
          <strong>回放</strong>
          <span>时间轴与事件</span>
        </button>
        <button type="button" @click="openCameraRecordings">
          <strong>录像管理</strong>
          <span>片段与归档</span>
        </button>
      </div>
    </section>
  </Teleport>

  <Teleport v-if="selectedCameraId && motionPortalReady" to=".camera-detail-drawer .drawer-body-v2">
    <section class="event-detection-portal-section" aria-label="事件检测">
      <div class="event-detection-portal-copy">
        <span class="portal-eyebrow">事件检测</span>
        <strong>本地移动检测</strong>
        <small>这里只显示当前检测状态；灵敏度、事件策略与检测区域统一在事件检测工作区配置。</small>
      </div>
      <div class="event-detection-portal-status">
        <span class="portal-status-pill" :class="{ active: motionEnabled, error: detectionError }">{{ motionRuntimeLabel }}</span>
        <small>{{ motionZoneSummary }}</small>
        <el-button text type="primary" :disabled="detectionLoading" @click="openEventDetection">前往配置</el-button>
      </div>
    </section>
  </Teleport>

  <el-dialog
    v-model="batchVisible"
    class="batch-camera-dialog"
    width="min(960px, calc(100vw - 36px))"
    align-center
    destroy-on-close
    :show-close="true"
    title="批量添加摄像头"
    @closed="closeBatch"
  >
    <BatchCamerasView
      @completed="onBatchCompleted"
      @close="closeBatch"
    />
  </el-dialog>
</template>

<style scoped>
.event-detection-portal-section {
  order: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 15px;
  border: 1px solid var(--nvr-border);
  border-radius: 10px;
  background: var(--nvr-surface);
}
.event-detection-portal-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.event-detection-portal-copy .portal-eyebrow {
  color: var(--nvr-blue);
  font-size: 9px;
  font-weight: 650;
  letter-spacing: .08em;
}
.event-detection-portal-copy strong {
  color: var(--nvr-text);
  font-size: 12px;
  font-weight: 650;
}
.event-detection-portal-copy small,
.event-detection-portal-status small {
  color: var(--nvr-muted);
  font-size: 10px;
  line-height: 1.45;
}
.event-detection-portal-status {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.portal-status-pill {
  padding: 4px 8px;
  border: 1px solid var(--nvr-border);
  border-radius: 999px;
  color: var(--nvr-muted);
  background: var(--nvr-surface-2);
  font-size: 10px;
  white-space: nowrap;
}
.portal-status-pill.active {
  color: var(--nvr-green);
  border-color: color-mix(in srgb, var(--nvr-green) 30%, var(--nvr-border));
}
.portal-status-pill.error {
  color: var(--nvr-red);
  border-color: color-mix(in srgb, var(--nvr-red) 30%, var(--nvr-border));
}
:global(.camera-detail-drawer .detail-columns),
:global(.camera-detail-drawer .runtime-section),
:global(.camera-detail-drawer .drawer-danger-zone) {
  order: 2;
}
:global(.batch-camera-dialog) {
  overflow: hidden;
  border: 1px solid var(--nvr-border-strong) !important;
  border-radius: 12px !important;
  background: var(--nvr-surface) !important;
}
:global(.batch-camera-dialog .el-dialog__header) {
  margin: 0;
  padding: 15px 18px;
  border-bottom: 1px solid var(--nvr-border);
  background: var(--nvr-surface-2);
}
:global(.batch-camera-dialog .el-dialog__title) {
  color: var(--nvr-text);
  font-size: 14px;
  font-weight: 650;
}
:global(.batch-camera-dialog .el-dialog__body) {
  padding: 0;
  background: var(--nvr-bg);
}
@media (max-width: 720px) {
  .event-detection-portal-section,
  .event-detection-portal-status {
    align-items: flex-start;
    flex-direction: column;
  }
  :global(.batch-camera-dialog) {
    width: calc(100vw - 20px) !important;
  }
}
</style>
