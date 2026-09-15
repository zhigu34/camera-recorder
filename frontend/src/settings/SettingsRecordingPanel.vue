<script setup lang="ts">
import { computed } from 'vue'
import type { RuntimeSettingsDraft } from '../utils/runtimeSettings'
const settings = defineModel<RuntimeSettingsDraft>({ required: true })
const presets = [
  { label: '30 秒', value: 30 }, { label: '1 分钟', value: 60 }, { label: '2 分钟', value: 120 },
  { label: '3 分钟', value: 180 }, { label: '5 分钟', value: 300 }, { label: '10 分钟', value: 600 },
  { label: '15 分钟', value: 900 }, { label: '30 分钟', value: 1800 }, { label: '60 分钟', value: 3600 },
]
function durationText(seconds: number) {
  if (seconds < 60) return `${seconds} 秒`
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`
  return `${seconds} 秒`
}
const durationOptions = computed(() => {
  if (presets.some((option) => option.value === settings.value.segment_duration_seconds)) return presets
  return [...presets, { label: `当前自定义值 · ${durationText(settings.value.segment_duration_seconds)}`, value: settings.value.segment_duration_seconds }]
    .sort((a, b) => a.value - b.value)
})
</script>

<template>
  <section class="settings-section-page">
    <header class="settings-section-header"><span class="settings-section-kicker">RECORDER</span><h2>录像</h2><p>控制录像切片、流连接和媒体处理参数。</p></header>
    <div class="settings-group">
      <div class="settings-group-title"><strong>切片设置</strong><span>决定录像文件如何按时间生成。</span></div>
      <div class="setting-row">
        <div class="setting-copy"><strong>切片时长</strong><span>单个录像文件的目标长度，当前为 {{ durationText(settings.segment_duration_seconds) }}。</span><em class="activation-pill recorder">重启 Recorder 生效</em></div>
        <div class="setting-control"><el-select v-model="settings.segment_duration_seconds" placeholder="选择切片时长"><el-option v-for="option in durationOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></div>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>切片整点对齐</strong><span>按整点边界分割录像，例如 10:00、11:00，便于检索和跨日回放。</span><em class="activation-pill recorder">重启 Recorder 生效</em></div>
        <div class="setting-control setting-control-switch"><el-switch v-model="settings.align_segments_to_clock" /></div>
      </div>
    </div>
    <div class="settings-group">
      <div class="settings-group-title"><strong>流连接</strong><span>控制摄像头 RTSP 连接等待时间。</span></div>
      <div class="setting-row">
        <div class="setting-copy"><strong>RTSP 超时</strong><span>建议 3–10 秒。界面使用秒，保存时自动转换为后端使用的微秒。</span><em class="activation-pill recorder">下次连接生效</em></div>
        <div class="setting-control setting-number-unit"><el-input-number v-model="settings.rtsp_timeout_seconds" :min="0.5" :max="120" :step="0.5" :precision="1" /><span>秒</span></div>
      </div>
    </div>
    <div class="settings-group">
      <div class="settings-group-title"><strong>媒体处理</strong><span>控制录像文件整理任务的资源使用。</span></div>
      <div class="setting-row">
        <div class="setting-copy"><strong>Remux 并发</strong><span>同时进行 Remux 的最大任务数。数值越高，CPU 和 I/O 压力越大。</span><em class="activation-pill immediate">后续任务立即生效</em></div>
        <div class="setting-control setting-number-unit"><el-input-number v-model="settings.remux_concurrency" :min="1" :max="16" /><span>个</span></div>
      </div>
    </div>
  </section>
</template>
