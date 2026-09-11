<script setup lang="ts">
import App from './App.vue'
import BatchCamerasView from './BatchCamerasView.vue'
import PreviewView from './PreviewView.vue'
import SystemSettingsView from './SystemSettingsView.vue'

const path = window.location.pathname
const isSettings = path === '/settings'
const isBatchCameras = path === '/cameras/batch'
const isPreview = path === '/preview'

function openSettings() {
  window.location.href = '/settings'
}

function openBatchCameras() {
  window.location.href = '/cameras/batch'
}

function openPreview() {
  window.location.href = '/preview'
}
</script>

<template>
  <SystemSettingsView v-if="isSettings" />
  <BatchCamerasView v-else-if="isBatchCameras" />
  <PreviewView v-else-if="isPreview" />
  <template v-else>
    <App />
    <div class="quick-actions">
      <el-button type="success" @click="openPreview">实时预览</el-button>
      <el-button type="success" plain @click="openBatchCameras">批量添加摄像头</el-button>
      <el-button type="primary" @click="openSettings">系统设置</el-button>
    </div>
  </template>
</template>

<style scoped>
.quick-actions {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
}
.quick-actions :deep(.el-button) {
  margin-left: 0;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.14);
}
</style>
