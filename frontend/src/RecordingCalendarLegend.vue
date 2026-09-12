<template>
  <Teleport to=".page-shell > .el-card:nth-child(3) .el-card__body" defer>
    <div class="calendar-legend" aria-label="录像日历图例">
      <span><i class="calendar-swatch has-recordings" />有录像</span>
      <span><i class="calendar-swatch cloud" />含云端归档</span>
      <span><i class="calendar-swatch warning" />有告警 / 异常</span>
      <span><i class="calendar-swatch selected" />当前选中日期</span>
    </div>
  </Teleport>
</template>

<style scoped>
.calendar-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  margin-top: 12px;
  color: var(--nvr-muted);
  font-size: 10px;
}
.calendar-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.calendar-swatch {
  display: inline-block;
  width: 16px;
  height: 12px;
  border: 1px solid var(--nvr-border);
  border-radius: 3px;
  box-sizing: border-box;
  background: var(--nvr-surface-2);
}
.calendar-swatch.has-recordings {
  background: color-mix(in srgb, var(--nvr-green) 6%, var(--nvr-surface-2));
  border-color: color-mix(in srgb, var(--nvr-green) 24%, var(--nvr-border));
}
.calendar-swatch.cloud {
  background: color-mix(in srgb, var(--nvr-green) 6%, var(--nvr-surface-2));
  border-color: color-mix(in srgb, var(--nvr-green) 24%, var(--nvr-border));
  box-shadow: inset 0 -2px 0 var(--nvr-purple);
}
.calendar-swatch.warning {
  background: color-mix(in srgb, var(--nvr-green) 6%, var(--nvr-surface-2));
  border: 2px solid var(--nvr-yellow);
}
.calendar-swatch.selected {
  background: color-mix(in srgb, var(--nvr-blue) 8%, var(--nvr-surface-2));
  border: 2px solid var(--nvr-blue);
}
</style>
