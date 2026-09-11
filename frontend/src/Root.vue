<script setup lang="ts">
import App from './App.vue'
import SystemSettingsView from './SystemSettingsView.vue'

const isSettings = window.location.pathname === '/settings'

function openSettings() {
  window.location.href = '/settings'
}
</script>

<template>
  <SystemSettingsView v-if="isSettings" />
  <template v-else>
    <App />
    <el-button class="settings-fab" type="primary" @click="openSettings">系统设置</el-button>
  </template>
</template>

<style scoped>
.settings-fab {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 3000;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.16);
}
</style>
