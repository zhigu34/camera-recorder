<script setup lang="ts">
import { computed } from 'vue'

import type { CameraReliability, RecordingGapDiagnostic } from '../../stores/healthReliability'
import type { CameraHealth } from '../../stores/runtime'
import {
  confidenceLabel,
  connectivityLabel,
  formatDuration,
  formatRate,
  formatTime,
  recorderLabel,
  scheduleLabel,
  verdictLabel,
  verdictType,
} from '../../utils/healthDisplay'

const props = defineProps<{
  modelValue: boolean
  realtime: CameraHealth | null
  reliability: CameraReliability | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  playback: [diagnostic: RecordingGapDiagnostic]
  camera: [cameraId: number]
  events: [cameraId: number]
}>()

const title = computed(() => props.realtime?.name || props.reliability?.name || '摄像头诊断')
const cameraId = computed(() => props.realtime?.camera_id || props.reliability?.camera_id || null)
</script>

<template>
  <el-drawer :model-value="modelValue" size="520px" direction="rtl" :with-header="false" @update:model-value="emit('update:modelValue', $event)">
    <div class="drawer-shell">
      <header>
        <div><span>DIAGNOSTICS</span><h2>{{ title }}</h2><small>{{ realtime?.ip || reliability?.ip || '' }}</small></div>
        <button type="button" aria-label="关闭" @click="emit('update:modelValue', false)">×</button>
      </header>

      <section class="current-section">
        <div class="section-title"><h3>实时状态</h3><small>打开诊断不会启动任何视频流</small></div>
        <div class="facts">
          <div><span>连接</span><strong>{{ connectivityLabel(realtime?.connectivity_status || 'unknown') }}</strong></div>
          <div><span>Recorder</span><strong>{{ recorderLabel(realtime?.recorder_state || 'STOPPED') }}</strong></div>
          <div><span>计划</span><strong>{{ scheduleLabel(realtime?.schedule_state || 'disabled') }}</strong></div>
          <div><span>重启次数</span><strong>{{ realtime?.restart_count ?? 0 }}</strong></div>
        </div>
        <p v-if="realtime?.last_error" class="runtime-error">{{ realtime.last_error }}</p>
      </section>

      <section class="window-section">
        <div class="section-title"><h3>所选周期可靠性</h3><span v-if="reliability" class="verdict" :class="verdictType(reliability.verdict)">{{ verdictLabel(reliability.verdict) }}</span></div>
        <div v-if="reliability" class="facts reliability-facts">
          <div><span>Recorder 可用率</span><strong>{{ formatRate(reliability.recorder_availability_rate) }}</strong></div>
          <div><span>录像完整率</span><strong>{{ formatRate(reliability.recording_completeness) }}</strong></div>
          <div><span>缺片段</span><strong>{{ reliability.recording_gap_count }}</strong></div>
          <div><span>缺失时长</span><strong>{{ formatDuration(reliability.missing_recording_seconds) }}</strong></div>
        </div>
        <div v-else class="empty-state">该设备暂无所选周期的历史可靠性数据，实时状态仍可用。</div>
      </section>

      <section class="diagnostics-section">
        <div class="section-title"><h3>诊断详情</h3><small>按时间显示缺口原因与证据置信度</small></div>
        <div v-if="reliability?.diagnostics.length" class="diagnostics">
          <article v-for="diagnostic in reliability.diagnostics" :key="`${diagnostic.start_at}-${diagnostic.end_at}`">
            <div class="diagnostic-head"><strong>{{ diagnostic.cause_label }}</strong><time>{{ formatTime(diagnostic.start_at) }}</time></div>
            <dl>
              <div><dt>原因</dt><dd>{{ diagnostic.cause_label }}</dd></div>
              <div><dt>诊断详情</dt><dd>{{ diagnostic.detail }}</dd></div>
              <div><dt>置信度</dt><dd>{{ confidenceLabel(diagnostic.confidence) }}</dd></div>
              <div><dt>影响时长</dt><dd>{{ formatDuration(diagnostic.duration_seconds) }}</dd></div>
            </dl>
            <button type="button" class="playback-action" @click="emit('playback', diagnostic)">查看回放</button>
          </article>
        </div>
        <div v-else class="empty-state">所选周期没有可展开的缺片段诊断。</div>
      </section>

      <footer>
        <button v-if="cameraId" type="button" @click="emit('events', cameraId)">相关事件</button>
        <button v-if="cameraId" type="button" class="primary" @click="emit('camera', cameraId)">摄像头设置</button>
      </footer>
    </div>
  </el-drawer>
</template>

<style scoped>
.drawer-shell{min-height:100%;display:flex;flex-direction:column;color:var(--nvr-text);background:var(--nvr-bg)}header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:17px 18px;border-bottom:1px solid var(--nvr-border);background:var(--nvr-surface)}header span{color:var(--nvr-subtle);font-size:8px;font-weight:800;letter-spacing:.15em}header h2{margin:4px 0 2px;font-size:16px;font-weight:650}header small{color:var(--nvr-muted);font-size:9px}header button{width:28px;height:28px;border:0;border-radius:7px;background:transparent;color:var(--nvr-muted);font-size:20px;cursor:pointer}header button:hover{background:var(--nvr-hover);color:var(--nvr-text)}section{padding:14px 18px;border-bottom:1px solid var(--nvr-border)}.section-title{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.section-title h3{margin:0;font-size:11px;font-weight:650}.section-title small{color:var(--nvr-subtle);font-size:8px}.facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;overflow:hidden;border:1px solid var(--nvr-border);border-radius:7px;background:var(--nvr-border)}.facts>div{display:flex;min-height:54px;flex-direction:column;justify-content:center;gap:4px;padding:8px 10px;background:var(--nvr-surface)}.facts span{color:var(--nvr-subtle);font-size:8px}.facts strong{font-size:10px;font-weight:600}.runtime-error{margin:8px 0 0;padding:8px 9px;border-radius:6px;background:color-mix(in srgb,var(--nvr-red) 6%,transparent);color:var(--nvr-red);font-size:9px;line-height:1.45}.verdict{display:inline-flex;padding:2px 6px;border-radius:999px;font-size:8px}.verdict.success{color:var(--nvr-green);background:color-mix(in srgb,var(--nvr-green) 8%,transparent)}.verdict.danger{color:var(--nvr-red);background:color-mix(in srgb,var(--nvr-red) 8%,transparent)}.verdict.warning{color:var(--nvr-yellow);background:color-mix(in srgb,var(--nvr-yellow) 8%,transparent)}.verdict.info{color:var(--nvr-muted);background:var(--nvr-surface-2)}.diagnostics{display:flex;flex-direction:column;gap:7px}.diagnostics article{padding:10px;border:1px solid var(--nvr-border);border-radius:7px;background:var(--nvr-surface)}.diagnostic-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.diagnostic-head strong{font-size:10px}.diagnostic-head time{color:var(--nvr-subtle);font-size:8px}dl{margin:8px 0 0}dl>div{display:grid;grid-template-columns:68px minmax(0,1fr);gap:8px;padding:4px 0}dt{color:var(--nvr-subtle);font-size:8px}dd{margin:0;color:var(--nvr-text-soft);font-size:9px;line-height:1.45}.playback-action{margin-top:8px;border:1px solid var(--nvr-border);border-radius:6px;padding:5px 8px;background:transparent;color:var(--nvr-text-soft);font-size:9px;cursor:pointer}.playback-action:hover{border-color:var(--nvr-blue);color:var(--nvr-text)}.empty-state{padding:18px 8px;color:var(--nvr-muted);font-size:9px;text-align:center}footer{display:flex;justify-content:flex-end;gap:7px;margin-top:auto;padding:13px 18px;background:var(--nvr-surface)}footer button{border:1px solid var(--nvr-border);border-radius:7px;padding:6px 10px;background:transparent;color:var(--nvr-text-soft);font-size:9px;cursor:pointer}footer .primary{border-color:var(--nvr-blue);background:var(--nvr-blue);color:#fff}
@media(max-width:560px){.facts{grid-template-columns:1fr}}
</style>
