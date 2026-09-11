<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

const legend = ref<HTMLElement | null>(null)

onMounted(async () => {
  await nextTick()
  const timeline = document.querySelector('.timeline')
  if (timeline && legend.value) {
    timeline.insertAdjacentElement('afterend', legend.value)
  }
})
</script>

<template>
  <div ref="legend" class="timeline-legend" aria-label="时间轴图例">
    <span><i class="legend-dot healthy" />健康录像</span>
    <span><i class="legend-dot warning" />有警告</span>
    <span><i class="legend-dot unhealthy" />异常录像</span>
    <span><i class="legend-dot cloud" />仅云端</span>
    <span><i class="legend-dot gap" />录像缺口</span>
    <span><i class="legend-dot deleted" />不可播放</span>
    <span><i class="legend-dot active" />当前播放</span>
  </div>
</template>

<style scoped>
.timeline-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 18px;
  margin-top: 12px;
  color: #606266;
  font-size: 13px;
}
.timeline-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.legend-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  box-sizing: border-box;
}
.legend-dot.healthy { background: #67c23a; }
.legend-dot.warning { background: #e6a23c; }
.legend-dot.unhealthy { background: #f56c6c; }
.legend-dot.cloud { background: #7c3aed; }
.legend-dot.gap {
  background: repeating-linear-gradient(
    135deg,
    rgba(230, 162, 60, .55) 0,
    rgba(230, 162, 60, .55) 3px,
    rgba(230, 162, 60, .12) 3px,
    rgba(230, 162, 60, .12) 6px
  );
  border: 1px solid rgba(230, 162, 60, .45);
}
.legend-dot.deleted { background: #c0c4cc; }
.legend-dot.active {
  background: #67c23a;
  border: 2px solid #409eff;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, .25);
}
</style>
