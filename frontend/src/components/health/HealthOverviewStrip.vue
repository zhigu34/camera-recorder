<script setup lang="ts">
import { computed } from 'vue'

import type { HealthReliabilityReport } from '../../stores/healthReliability'
import type { RealtimeHealthSnapshot } from '../../stores/runtime'
import { formatDuration, formatRate } from '../../utils/healthDisplay'

const props = defineProps<{
  realtime: RealtimeHealthSnapshot | null
  reliability: HealthReliabilityReport | null
}>()

const overall = computed(() => props.reliability?.overall)
const realtimeLabel = computed(() => {
  const abnormal = props.realtime?.cameras.abnormal ?? 0
  if (!props.realtime) return '等待实时状态'
  return abnormal ? `${abnormal} 台需要关注` : '实时状态正常'
})
</script>

<template>
  <section class="overview-strip" aria-label="健康摘要">
    <article>
      <span>实时状态</span>
      <strong>{{ realtimeLabel }}</strong>
      <small>{{ realtime?.cameras.recording ?? '-' }} 路录像 · {{ realtime?.cameras.online ?? '-' }} 路在线</small>
    </article>
    <article>
      <span>Recorder 可用率</span>
      <strong>{{ formatRate(overall?.recorder_availability_rate) }}</strong>
      <small>所选周期的应录像时段</small>
    </article>
    <article>
      <span>录像完整率</span>
      <strong>{{ formatRate(overall?.recording_completeness) }}</strong>
      <small>{{ overall?.recording_gap_count ?? 0 }} 个缺片段</small>
    </article>
    <article>
      <span>缺失录像</span>
      <strong>{{ formatDuration(overall?.missing_recording_seconds) }}</strong>
      <small>{{ overall?.unexplained_recording_gaps ?? 0 }} 个原因未知</small>
    </article>
  </section>
</template>

<style scoped>
.overview-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));overflow:hidden;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}
.overview-strip article{min-height:78px;padding:13px 15px;border-right:1px solid var(--nvr-border)}.overview-strip article:last-child{border-right:0}.overview-strip span{display:block;color:var(--nvr-muted);font-size:9px}.overview-strip strong{display:block;margin:7px 0 3px;font-size:16px;font-weight:650;letter-spacing:-.02em}.overview-strip small{color:var(--nvr-subtle);font-size:9px}
@media(max-width:860px){.overview-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-strip article:nth-child(2){border-right:0}.overview-strip article:nth-child(-n+2){border-bottom:1px solid var(--nvr-border)}}
@media(max-width:540px){.overview-strip{grid-template-columns:1fr}.overview-strip article{border-right:0;border-bottom:1px solid var(--nvr-border)}.overview-strip article:last-child{border-bottom:0}}
</style>
