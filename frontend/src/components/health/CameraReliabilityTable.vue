<script setup lang="ts">
import type { CameraReliability } from '../../stores/healthReliability'
import { formatDuration, formatRate, verdictLabel, verdictType } from '../../utils/healthDisplay'

const props = defineProps<{
  cameras: CameraReliability[]
}>()
const emit = defineEmits<{ select: [cameraId: number] }>()
</script>

<template>
  <section class="reliability-panel">
    <header>
      <div><span>RELIABILITY</span><h2>摄像头可靠性</h2></div>
      <small>点击设备查看缺片段、断流与证据详情</small>
    </header>
    <div class="table-scroll">
      <table>
        <thead><tr><th>摄像头</th><th>结论</th><th>Recorder 可用率</th><th>录像完整率</th><th>缺片段</th><th>缺失时长</th><th>最近原因</th></tr></thead>
        <tbody>
          <tr v-for="camera in props.cameras" :key="camera.camera_id" :class="{ muted: !camera.monitored }" tabindex="0" @click="emit('select', camera.camera_id)" @keydown.enter="emit('select', camera.camera_id)">
            <td><strong>{{ camera.name }}</strong><small>{{ camera.ip }}</small></td>
            <td><span class="verdict" :class="verdictType(camera.verdict)">{{ verdictLabel(camera.verdict) }}</span></td>
            <td>{{ formatRate(camera.recorder_availability_rate) }}</td>
            <td>{{ formatRate(camera.recording_completeness) }}</td>
            <td><b :class="{ bad: camera.recording_gap_count > 0 }">{{ camera.recording_gap_count }}</b></td>
            <td>{{ formatDuration(camera.missing_recording_seconds) }}</td>
            <td class="reason">{{ camera.primary_problem?.detail || camera.reasons[0] || '—' }}</td>
          </tr>
          <tr v-if="!props.cameras.length" class="empty"><td colspan="7">暂无可靠性数据</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.reliability-panel{border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface);overflow:hidden}.reliability-panel>header{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;padding:11px 14px;border-bottom:1px solid var(--nvr-border)}header span{color:var(--nvr-subtle);font-size:8px;font-weight:800;letter-spacing:.15em}h2{margin:3px 0 0;font-size:12px;font-weight:650}header small{color:var(--nvr-subtle);font-size:8px}.table-scroll{overflow:auto}table{width:100%;min-width:850px;border-collapse:collapse}th,td{padding:9px 12px;border-bottom:1px solid var(--nvr-border);font-size:9px;text-align:left;white-space:nowrap}th{color:var(--nvr-subtle);font-size:8px;font-weight:650;background:color-mix(in srgb,var(--nvr-surface) 88%,var(--nvr-bg))}tbody tr{cursor:pointer}tbody tr:hover,tbody tr:focus{background:var(--nvr-hover);outline:none}tbody tr:last-child td{border-bottom:0}td:first-child{display:flex;min-width:150px;flex-direction:column;gap:2px}td:first-child strong{font-size:10px;font-weight:600}td:first-child small{color:var(--nvr-subtle);font-size:8px}.verdict{display:inline-flex;padding:2px 6px;border-radius:999px;font-size:8px}.verdict.success{color:var(--nvr-green);background:color-mix(in srgb,var(--nvr-green) 8%,transparent)}.verdict.danger{color:var(--nvr-red);background:color-mix(in srgb,var(--nvr-red) 8%,transparent)}.verdict.warning{color:var(--nvr-yellow);background:color-mix(in srgb,var(--nvr-yellow) 8%,transparent)}.verdict.info{color:var(--nvr-muted);background:var(--nvr-surface-2)}.bad{color:var(--nvr-red)}.reason{max-width:280px;overflow:hidden;color:var(--nvr-muted);text-overflow:ellipsis}.muted{opacity:.62}.empty td{padding:28px;text-align:center;color:var(--nvr-muted);cursor:default}
</style>
