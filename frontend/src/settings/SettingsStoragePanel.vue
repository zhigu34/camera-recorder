<script setup lang="ts">
import type { RuntimeSettingsDraft } from '../utils/runtimeSettings'
const settings = defineModel<RuntimeSettingsDraft>({ required: true })
</script>

<template>
  <section class="settings-section-page">
    <header class="settings-section-header"><span class="settings-section-kicker">STORAGE</span><h2>存储</h2><p>定义本地录像盘的容量风险边界和本地录像保留策略。</p></header>
    <div class="settings-group">
      <div class="settings-group-title"><strong>磁盘保护</strong><span>达到阈值后，系统状态和告警进入对应级别。</span></div>
      <div class="setting-row">
        <div class="setting-copy"><strong>告警阈值</strong><span>达到该占用率后进入 warning。</span><em class="activation-pill immediate">立即生效</em></div>
        <div class="setting-control setting-number-unit"><el-input-number v-model="settings.storage_warning_percent" :min="1" :max="99" /><span>%</span></div>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>严重告警阈值</strong><span>必须高于普通告警阈值；达到后进入 critical。</span><em class="activation-pill immediate">立即生效</em></div>
        <div class="setting-control setting-number-unit"><el-input-number v-model="settings.storage_critical_percent" :min="1" :max="100" /><span>%</span></div>
      </div>
      <div class="storage-threshold-preview" aria-label="磁盘阈值预览">
        <div class="threshold-rail"><span class="warning-mark" :style="{ left: `${settings.storage_warning_percent}%` }"></span><span class="critical-mark" :style="{ left: `${settings.storage_critical_percent}%` }"></span></div>
        <div class="threshold-legend"><span>0%</span><span class="warning-text">告警 {{ settings.storage_warning_percent }}%</span><span class="critical-text">严重 {{ settings.storage_critical_percent }}%</span><span>100%</span></div>
      </div>
    </div>
    <div class="settings-group">
      <div class="settings-group-title"><strong>本地保留</strong><span>控制归档成功后的本地录像保留时间。</span></div>
      <div class="setting-row">
        <div class="setting-copy"><strong>本地录像保留时间</strong><span>-1 表示永久保留；其他值表示归档成功后继续保留的小时数。</span><em class="activation-pill immediate">立即生效</em></div>
        <div class="setting-control setting-number-unit"><el-input-number v-model="settings.local_retention_hours" :min="-1" :max="87600" /><span>小时</span></div>
      </div>
    </div>
  </section>
</template>
