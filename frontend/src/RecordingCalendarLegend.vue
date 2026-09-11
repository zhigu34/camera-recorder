<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

const legend = ref<HTMLElement | null>(null)

onMounted(async () => {
  await nextTick()
  const calendar = document.querySelector('.recording-calendar')
  if (calendar && legend.value) {
    calendar.insertAdjacentElement('afterend', legend.value)
  }
})
</script>

<template>
  <div ref="legend" class="calendar-legend" aria-label="录像日历图例">
    <span><i class="calendar-swatch has-recordings" />有录像</span>
    <span><i class="calendar-swatch cloud" />含云端归档</span>
    <span><i class="calendar-swatch warning" />有告警 / 异常</span>
    <span><i class="calendar-swatch selected" />当前选中日期</span>
  </div>
</template>

<style scoped>
.calendar-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 18px;
  margin-top: 12px;
  color: #606266;
  font-size: 13px;
}
.calendar-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.calendar-swatch {
  display: inline-block;
  width: 18px;
  height: 14px;
  border-radius: 3px;
  box-sizing: border-box;
  background: #fafafa;
  border: 1px solid #dcdfe6;
}
.calendar-swatch.has-recordings {
  background: #f0f9eb;
  border-color: #b3e19d;
}
.calendar-swatch.cloud {
  background: #f0f9eb;
  border-color: #b3e19d;
  box-shadow: inset 0 -3px 0 #7c3aed;
}
.calendar-swatch.warning {
  background: #f0f9eb;
  border: 2px solid #e6a23c;
}
.calendar-swatch.selected {
  background: #fafafa;
  border: 2px solid #409eff;
}
</style>
