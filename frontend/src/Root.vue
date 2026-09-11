<script setup lang="ts">
import App from './App.vue'
import BatchCamerasView from './BatchCamerasView.vue'
import HealthView from './HealthView.vue'
import PlaybackTelemetryBridge from './PlaybackTelemetryBridge.vue'
import PreviewView from './PreviewView.vue'
import RecordingBrowserViewV3 from './RecordingBrowserViewV3.vue'
import RecordingCalendarLegend from './RecordingCalendarLegend.vue'
import RecordingTimelineLegend from './RecordingTimelineLegend.vue'
import SystemSettingsView from './SystemSettingsView.vue'

const path = window.location.pathname
const isSettings = path === '/settings'
const isBatchCameras = path === '/cameras/batch'
const isPreview = path === '/preview'
const isHealth = path === '/health-center'
const isRecordingBrowser = path === '/recordings/browser'

function openSettings() {
  window.location.href = '/settings'
}

function openBatchCameras() {
  window.location.href = '/cameras/batch'
}

function openPreview() {
  window.location.href = '/preview'
}

function openHealth() {
  window.location.href = '/health-center'
}

function openRecordingBrowser() {
  window.location.href = '/recordings/browser'
}
</script>

<template>
  <SystemSettingsView v-if="isSettings" />
  <BatchCamerasView v-else-if="isBatchCameras" />
  <PreviewView v-else-if="isPreview" />
  <HealthView v-else-if="isHealth" />
  <template v-else-if="isRecordingBrowser">
    <RecordingBrowserViewV3 />
    <PlaybackTelemetryBridge />
    <RecordingCalendarLegend />
    <RecordingTimelineLegend />
  </template>
  <template v-else>
    <App />
    <div class="quick-actions">
      <el-button type="primary" plain @click="openRecordingBrowser">录像浏览</el-button>
      <el-button type="warning" plain @click="openHealth">系统健康</el-button>
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
