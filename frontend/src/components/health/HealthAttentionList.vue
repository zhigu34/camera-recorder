<script setup lang="ts">
import { computed } from 'vue'

import type { ReliabilityIssue } from '../../stores/healthReliability'
import type { CameraHealth } from '../../stores/runtime'
import { formatTime } from '../../utils/healthDisplay'

const props = defineProps<{
  realtimeCameras: CameraHealth[]
  historicalIssues: ReliabilityIssue[]
}>()
const emit = defineEmits<{ select: [cameraId: number] }>()

interface AttentionItem {
  key: string
  severity: 'error' | 'warning'
  cameraId: number
  title: string
  detail: string
  time?: string | null
}

const items = computed<AttentionItem[]>(() => {
  const active = props.realtimeCameras
    .filter((camera) => camera.abnormal)
    .map((camera) => ({
      key: `realtime-${camera.camera_id}`,
      severity: 'error' as const,
      cameraId: camera.camera_id,
      title: `${camera.name} 当前状态异常`,
      detail: camera.last_error || (camera.connectivity_status === 'offline' ? '摄像头当前离线' : `Recorder 当前为 ${camera.recorder_state}`),
      time: camera.offline_since,
    }))

  const activeCameraIds = new Set(active.map((item) => item.cameraId))
  const historical = props.historicalIssues
    .filter((issue) => typeof issue.camera_id === 'number' && !activeCameraIds.has(issue.camera_id))
    .slice(0, 8)
    .map((issue) => ({
      key: `historical-${issue.kind}-${issue.camera_id}-${issue.started_at || issue.title}`,
      severity: issue.severity === 'error' ? 'error' as const : 'warning' as const,
      cameraId: Number(issue.camera_id),
      title: issue.title,
      detail: issue.detail,
      time: issue.started_at,
    }))

  return [...active, ...historical].slice(0, 10)
})
</script>

<template>
  <section class="attention-panel">
    <header>
      <div><span>ATTENTION</span><h2>需要关注</h2></div>
      <small>当前异常优先，其次显示所选周期的可靠性问题</small>
    </header>
    <div v-if="items.length" class="attention-list">
      <button v-for="item in items" :key="item.key" type="button" @click="emit('select', item.cameraId)">
        <i :class="item.severity"></i>
        <span class="copy"><strong>{{ item.title }}</strong><small>{{ item.detail }}</small></span>
        <time>{{ item.time ? formatTime(item.time) : '查看诊断' }}</time>
        <b>›</b>
      </button>
    </div>
    <div v-else class="quiet-state">
      <strong>当前没有需要处理的健康问题</strong>
      <span>实时状态正常，所选周期也没有检测到需要关注的可靠性异常。</span>
    </div>
  </section>
</template>

<style scoped>
.attention-panel{border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface);overflow:hidden}.attention-panel>header{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;padding:11px 14px;border-bottom:1px solid var(--nvr-border)}header span{color:var(--nvr-subtle);font-size:8px;font-weight:800;letter-spacing:.15em}h2{margin:3px 0 0;font-size:12px;font-weight:650}header small{color:var(--nvr-subtle);font-size:8px}.attention-list button{display:grid;width:100%;grid-template-columns:8px minmax(0,1fr) auto 10px;align-items:center;gap:9px;padding:10px 14px;border:0;border-bottom:1px solid var(--nvr-border);background:transparent;color:inherit;text-align:left;cursor:pointer}.attention-list button:last-child{border-bottom:0}.attention-list button:hover{background:var(--nvr-hover)}.attention-list i{width:6px;height:6px;border-radius:50%}.attention-list i.error{background:var(--nvr-red)}.attention-list i.warning{background:var(--nvr-yellow)}.copy{display:flex;min-width:0;flex-direction:column;gap:3px}.copy strong{font-size:10px;font-weight:600}.copy small{overflow:hidden;color:var(--nvr-muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.attention-list time{color:var(--nvr-subtle);font-size:8px;white-space:nowrap}.attention-list b{color:var(--nvr-subtle);font-size:13px}.quiet-state{display:flex;min-height:86px;flex-direction:column;align-items:center;justify-content:center;gap:5px;padding:16px;color:var(--nvr-muted);text-align:center}.quiet-state strong{color:var(--nvr-text-soft);font-size:10px}.quiet-state span{font-size:8px}
@media(max-width:700px){.attention-panel>header{align-items:flex-start;flex-direction:column}.attention-list button{grid-template-columns:8px minmax(0,1fr) 10px}.attention-list time{display:none}}
</style>
