<template>
  <Teleport to=".page-shell > .el-card:nth-child(4) .el-card__body" defer>
    <div class="timeline-legend" aria-label="时间轴图例">
      <span><i class="legend-dot healthy" />健康录像</span>
      <span><i class="legend-dot warning" />有警告</span>
      <span><i class="legend-dot unhealthy" />异常录像</span>
      <span><i class="legend-dot cloud" />仅云端</span>
      <span><i class="legend-dot gap" />录像缺口</span>
      <span><i class="legend-dot deleted" />不可播放</span>
      <span><i class="legend-dot active" />当前播放</span>
    </div>
  </Teleport>
</template>

<style scoped>
.timeline-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  margin-top: 12px;
  color: var(--nvr-muted);
  font-size: 10px;
}
.timeline-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.legend-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
  box-sizing: border-box;
}
.legend-dot.healthy { background: var(--nvr-green); }
.legend-dot.warning { background: var(--nvr-yellow); }
.legend-dot.unhealthy { background: var(--nvr-red); }
.legend-dot.cloud { background: var(--nvr-purple); }
.legend-dot.gap {
  border: 1px solid color-mix(in srgb, var(--nvr-yellow) 45%, var(--nvr-border));
  background: repeating-linear-gradient(
    135deg,
    color-mix(in srgb, var(--nvr-yellow) 55%, transparent) 0,
    color-mix(in srgb, var(--nvr-yellow) 55%, transparent) 3px,
    color-mix(in srgb, var(--nvr-yellow) 12%, transparent) 3px,
    color-mix(in srgb, var(--nvr-yellow) 12%, transparent) 6px
  );
}
.legend-dot.deleted { background: var(--nvr-subtle); opacity: .55; }
.legend-dot.active {
  background: var(--nvr-green);
  border: 2px solid var(--nvr-blue);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--nvr-blue) 25%, transparent);
}
</style>
