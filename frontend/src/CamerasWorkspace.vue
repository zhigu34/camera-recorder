<script setup lang="ts">
import { ref } from 'vue'
import BatchCamerasView from './BatchCamerasView.vue'
import CamerasView from './CamerasView.vue'

const emit = defineEmits<{
  (event: 'open-preview'): void
}>()

const batchVisible = ref(false)
const cameraViewKey = ref(0)

function onBatchCompleted() {
  cameraViewKey.value += 1
}
</script>

<template>
  <CamerasView
    :key="cameraViewKey"
    @open-batch="batchVisible = true"
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
  >
    <BatchCamerasView
      @completed="onBatchCompleted"
      @close="batchVisible = false"
    />
  </el-dialog>
</template>

<style scoped>
:global(.batch-camera-dialog) {
  overflow: hidden;
  border: 1px solid var(--nvr-border-strong) !important;
  border-radius: 12px !important;
}
:global(.batch-camera-dialog .el-dialog__header) {
  margin: 0;
  padding: 15px 18px;
  border-bottom: 1px solid var(--nvr-border);
  background: #111820;
}
:global(.batch-camera-dialog .el-dialog__title) {
  color: var(--nvr-text);
  font-size: 14px;
  font-weight: 650;
}
:global(.batch-camera-dialog .el-dialog__body) {
  padding: 0;
}
@media (max-width: 720px) {
  :global(.batch-camera-dialog) {
    width: calc(100vw - 20px) !important;
  }
}
</style>
