<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BatchCamerasView from './BatchCamerasView.vue'
import CamerasView from './CamerasView.vue'
import MotionDetectionPanel from './MotionDetectionPanel.vue'
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
let portalObserver: MutationObserver | null = null

function refreshMotionPortalTarget() {
  if (!selectedCameraId.value) {
    motionPortalReady.value = false
    return
  }
  motionPortalReady.value = Boolean(document.querySelector('.camera-detail-drawer .drawer-body-v2'))
}

watch(() => route.path, (path) => {
  batchVisible.value = path === '/cameras/batch'
}, { immediate: true })

watch(() => route.query.camera_id, async () => {
  motionPortalReady.value = false
  await nextTick()
  refreshMotionPortalTarget()
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

onMounted(() => {
  portalObserver = new MutationObserver(refreshMotionPortalTarget)
  portalObserver.observe(document.body, { childList: true, subtree: true })
  refreshMotionPortalTarget()
})

onBeforeUnmount(() => {
  portalObserver?.disconnect()
  portalObserver = null
})
</script>

<template>
  <CamerasView
    :key="cameraViewKey"
    @open-batch="openBatch"
    @open-preview="emit('open-preview')"
  />

  <Teleport v-if="selectedCameraId && motionPortalReady" to=".camera-detail-drawer .drawer-body-v2">
    <section class="motion-portal-section">
      <MotionDetectionPanel :key="selectedCameraId" :camera-id="selectedCameraId" />
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
.motion-portal-section {
  order: 1;
  min-width: 0;
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
  :global(.batch-camera-dialog) {
    width: calc(100vw - 20px) !important;
  }
}
</style>
