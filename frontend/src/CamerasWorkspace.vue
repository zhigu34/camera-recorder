<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BatchCamerasView from './BatchCamerasView.vue'
import CamerasView from './CamerasView.vue'

const emit = defineEmits<{
  (event: 'open-preview'): void
}>()

const route = useRoute()
const router = useRouter()
const batchVisible = ref(false)
const cameraViewKey = ref(0)

watch(() => route.path, (path) => {
  batchVisible.value = path === '/cameras/batch'
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
</script>

<template>
  <CamerasView
    :key="cameraViewKey"
    @open-batch="openBatch"
    @open-preview="emit('open-preview')"
  />

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
:global(.camera-detail-pane .detail-columns),
:global(.camera-detail-pane .runtime-section),
:global(.camera-detail-pane .camera-device-management),
:global(.camera-detail-pane .drawer-danger-zone) {
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
