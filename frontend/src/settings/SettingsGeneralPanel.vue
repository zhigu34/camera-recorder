<script setup lang="ts">
import type { RuntimeSettingsDraft } from '../utils/runtimeSettings'
const settings = defineModel<RuntimeSettingsDraft>({ required: true })
</script>

<template>
  <section class="settings-section-page">
    <header class="settings-section-header">
      <span class="settings-section-kicker">SYSTEM</span>
      <h2>常规</h2>
      <p>配置系统标识和服务启动后的默认行为。</p>
    </header>
    <div class="settings-group">
      <div class="settings-group-title"><strong>系统</strong><span>影响整个 Camera Recorder 实例的基础设置。</span></div>
      <div class="setting-row">
        <div class="setting-copy"><strong>系统名称</strong><span>用于界面标识和部分通知内容。</span><em class="activation-pill immediate">立即生效</em></div>
        <div class="setting-control"><el-input v-model="settings.app_name" maxlength="128" /></div>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>启动时自动恢复录像</strong><span>服务启动后，根据摄像头配置和录像计划恢复 Recorder。</span><em class="activation-pill restart">下次服务启动生效</em></div>
        <div class="setting-control setting-control-switch"><el-switch v-model="settings.auto_start_enabled" /></div>
      </div>
    </div>
  </section>
</template>
