<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'

import {
  ZOOM_SPANS,
  clampViewport,
  findRecordingAtWallTime,
  motionEventOverlapsRecordings,
  moveTimelineRange,
  normalizeTimelineRange,
  rangePercent,
  recordingRange,
  resizeTimelineRange,
  timeAtPointer,
  timeAtTrackPointer,
  wallClockSeconds,
  zoomAround,
  type PlaybackZoom,
  type TimelineRecording,
  type TimelineSelectionRange,
} from './utils/playbackTimelineV3'

interface MotionEventItem {
  id: number
  started_at: string
  ended_at: string
}

type TimelineInteraction = 'idle' | 'pan' | 'playhead-drag' | 'range-start-drag' | 'range-end-drag' | 'range-move'

const props = defineProps<{
  cameraId: number
  date: string
  recordings: TimelineRecording[]
  activeWallSeconds?: number | null
  rangeSelectEnabled?: boolean
  selectedRange?: TimelineSelectionRange | null
}>()

const emit = defineEmits<{
  seek: [seconds: number]
  'seek-preview': [seconds: number]
  'range-change': [range: TimelineSelectionRange]
  'range-commit': [range: TimelineSelectionRange]
}>()

const zoomLevels: PlaybackZoom[] = ['24h', '6h', '1h', '15m']
const zoom = ref<PlaybackZoom>('24h')
const viewStart = ref(0)
const cursorSeconds = ref(typeof props.activeWallSeconds === 'number' ? props.activeWallSeconds : 12 * 3600)
const motionEvents = ref<MotionEventItem[]>([])
const motionError = ref('')
const overlayRef = ref<HTMLElement | null>(null)
const interaction = ref<TimelineInteraction>('idle')
const interactionStartX = ref(0)
const interactionViewStart = ref(0)
const interactionCursorStart = ref(cursorSeconds.value)
const interactionRangeStart = ref<TimelineSelectionRange | null>(null)
const dragMoved = ref(false)
const hoverSeconds = ref<number | null>(null)
const localRange = ref<TimelineSelectionRange | null>(
  props.selectedRange ? normalizeTimelineRange(props.selectedRange.start, props.selectedRange.end, 1) : null,
)
let suppressClickUntil = 0

const span = computed(() => ZOOM_SPANS[zoom.value])
const playheadSeconds = computed(() => Math.max(viewStart.value, Math.min(viewStart.value + span.value, cursorSeconds.value)))
const playheadRatio = computed(() => Math.max(0, Math.min(1, (playheadSeconds.value - viewStart.value) / span.value)))
const playheadStyle = computed(() => ({ left: `${playheadRatio.value * 100}%` }))
const playheadCovered = computed(() => Boolean(findRecordingAtWallTime(props.recordings, cursorSeconds.value)))
const hoverStyle = computed(() => {
  if (hoverSeconds.value === null) return null
  const ratio = Math.max(0, Math.min(1, (hoverSeconds.value - viewStart.value) / span.value))
  return { left: `${ratio * 100}%` }
})
const selectionLayout = computed(() => {
  const range = localRange.value
  if (!props.rangeSelectEnabled || !range) return null
  return rangePercent(range.start, range.end, viewStart.value, span.value)
})
const selectionStyle = computed(() => selectionLayout.value
  ? { left: `${selectionLayout.value.left}%`, width: `${selectionLayout.value.width}%` }
  : undefined)
const tickCount = computed(() => zoom.value === '24h' ? 13 : zoom.value === '6h' ? 13 : zoom.value === '1h' ? 13 : 16)
const ticks = computed(() => Array.from({ length: tickCount.value }, (_, index) => {
  const ratio = index / Math.max(1, tickCount.value - 1)
  const seconds = viewStart.value + span.value * ratio
  return { ratio, seconds, label: clockLabel(seconds, zoom.value === '15m') }
}))
const recordingBlocks = computed(() => props.recordings.flatMap((item) => {
  const range = recordingRange(item)
  if (!range) return []
  const layout = rangePercent(range.start, range.end, viewStart.value, span.value)
  return layout ? [{ item, ...layout }] : []
}))
const motionBlocks = computed(() => motionEvents.value.flatMap((event) => {
  if (!motionEventOverlapsRecordings(event, props.recordings)) return []
  const start = wallClockSeconds(event.started_at)
  const end = wallClockSeconds(event.ended_at)
  if (start === null || end === null) return []
  const layout = rangePercent(start, Math.max(start + 1, end), viewStart.value, span.value)
  return layout ? [{ event, ...layout }] : []
}))
const overviewBlocks = computed(() => props.recordings.flatMap((item) => {
  const range = recordingRange(item)
  if (!range) return []
  const layout = rangePercent(range.start, range.end, 0, 86400)
  return layout ? [{ item, ...layout }] : []
}))
const overviewViewport = computed(() => rangePercent(viewStart.value, viewStart.value + span.value, 0, 86400))

function clockLabel(seconds: number, showSeconds = false) {
  const value = Math.max(0, Math.min(86400, Math.round(seconds)))
  const h = Math.floor(value / 3600)
  const m = Math.floor((value % 3600) / 60)
  const s = value % 60
  return showSeconds
    ? `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function centerOn(seconds: number) {
  viewStart.value = clampViewport(seconds - span.value / 2, span.value)
}

function chooseZoom(next: PlaybackZoom, anchorRatio = playheadRatio.value) {
  if (next === zoom.value) return
  const nextSpan = ZOOM_SPANS[next]
  viewStart.value = zoomAround(viewStart.value, span.value, nextSpan, anchorRatio)
  zoom.value = next
}

function pointerTime(event: PointerEvent | WheelEvent, element = overlayRef.value) {
  if (!element) return cursorSeconds.value
  const rect = element.getBoundingClientRect()
  return timeAtTrackPointer(viewStart.value, span.value, event.clientX, rect.left, rect.width)
}

function seekAtPointer(event: PointerEvent) {
  if (props.rangeSelectEnabled) return
  if (interaction.value !== 'idle' || Date.now() < suppressClickUntil) return
  const target = pointerTime(event)
  cursorSeconds.value = target
  emit('seek', target)
}

function beginInteraction(event: PointerEvent, state: TimelineInteraction) {
  if (interaction.value !== 'idle') return
  interaction.value = state
  interactionStartX.value = event.clientX
  interactionViewStart.value = viewStart.value
  interactionCursorStart.value = cursorSeconds.value
  interactionRangeStart.value = localRange.value ? { ...localRange.value } : null
  dragMoved.value = false
  hoverSeconds.value = null
  overlayRef.value?.setPointerCapture?.(event.pointerId)
}

function startPan(event: PointerEvent) {
  if (span.value >= 86400) return
  beginInteraction(event, 'pan')
}

function startPlayheadDrag(event: PointerEvent) {
  if (props.rangeSelectEnabled) return
  beginInteraction(event, 'playhead-drag')
}

function startRangeResize(event: PointerEvent, edge: 'start' | 'end') {
  if (!props.rangeSelectEnabled || !localRange.value) return
  beginInteraction(event, edge === 'start' ? 'range-start-drag' : 'range-end-drag')
}

function startRangeStartDrag(event: PointerEvent) {
  startRangeResize(event, 'start')
}

function startRangeEndDrag(event: PointerEvent) {
  startRangeResize(event, 'end')
}

function startRangeMove(event: PointerEvent) {
  if (!props.rangeSelectEnabled || !localRange.value) return
  beginInteraction(event, 'range-move')
}

function handlePointerMove(event: PointerEvent) {
  const element = overlayRef.value
  if (!element) return
  const rect = element.getBoundingClientRect()
  if (!rect.width) return

  if (interaction.value === 'idle') {
    hoverSeconds.value = pointerTime(event, element)
    return
  }

  if (Math.abs(event.clientX - interactionStartX.value) > 2) dragMoved.value = true

  if (interaction.value === 'pan') {
    const deltaX = interactionStartX.value - event.clientX
    const deltaSeconds = (deltaX / rect.width) * span.value
    viewStart.value = clampViewport(interactionViewStart.value + deltaSeconds, span.value)
    return
  }

  if (interaction.value === 'playhead-drag') {
    cursorSeconds.value = pointerTime(event, element)
    return
  }

  const initialRange = interactionRangeStart.value
  if (!initialRange) return
  if (interaction.value === 'range-start-drag' || interaction.value === 'range-end-drag') {
    const edge = interaction.value === 'range-start-drag' ? 'start' : 'end'
    const next = resizeTimelineRange(initialRange, edge, pointerTime(event, element), 1)
    localRange.value = next
    emit('range-change', next)
    return
  }
  if (interaction.value === 'range-move') {
    const deltaSeconds = ((event.clientX - interactionStartX.value) / rect.width) * span.value
    const next = moveTimelineRange(initialRange, deltaSeconds)
    localRange.value = next
    emit('range-change', next)
  }
}

function finishInteraction(event: PointerEvent) {
  const state = interaction.value
  if (state === 'idle') return
  overlayRef.value?.releasePointerCapture?.(event.pointerId)
  suppressClickUntil = Date.now() + 160

  if (state === 'playhead-drag') {
    emit('seek', cursorSeconds.value)
  }
  if (state === 'range-start-drag' || state === 'range-end-drag' || state === 'range-move') {
    if (localRange.value) emit('range-commit', { ...localRange.value })
  }
  interaction.value = 'idle'
}

function cancelInteraction(event: PointerEvent) {
  if (interaction.value === 'idle') return
  overlayRef.value?.releasePointerCapture?.(event.pointerId)
  if (interaction.value === 'playhead-drag') cursorSeconds.value = interactionCursorStart.value
  if (interaction.value === 'range-start-drag' || interaction.value === 'range-end-drag' || interaction.value === 'range-move') {
    localRange.value = interactionRangeStart.value ? { ...interactionRangeStart.value } : null
  }
  interaction.value = 'idle'
  suppressClickUntil = Date.now() + 160
}

function clearHover() {
  if (interaction.value === 'idle') hoverSeconds.value = null
}

function handleWheel(event: WheelEvent) {
  event.preventDefault()
  if (interaction.value !== 'idle') return
  const element = overlayRef.value || event.currentTarget as HTMLElement
  const anchor = pointerTime(event, element)
  const ratio = Math.max(0, Math.min(1, (anchor - viewStart.value) / span.value))
  const current = zoomLevels.indexOf(zoom.value)
  const next = event.deltaY < 0 ? Math.min(zoomLevels.length - 1, current + 1) : Math.max(0, current - 1)
  chooseZoom(zoomLevels[next] || zoom.value, ratio)
}

function seekOverview(event: PointerEvent) {
  if (props.rangeSelectEnabled) return
  const element = event.currentTarget as HTMLElement
  const rect = element.getBoundingClientRect()
  const target = timeAtTrackPointer(0, 86400, event.clientX, rect.left, rect.width)
  cursorSeconds.value = target
  if (zoom.value !== '24h') centerOn(target)
  emit('seek', target)
}

async function loadMotionEvents() {
  motionError.value = ''
  try {
    const { data } = await axios.get<MotionEventItem[]>('/api/motion-events', {
      params: { camera_id: props.cameraId, start: `${props.date}T00:00:00`, end: `${props.date}T23:59:59.999999`, limit: 1000 },
    })
    motionEvents.value = data
  } catch {
    motionEvents.value = []
    motionError.value = '移动事件加载失败'
  }
}

watch(() => [props.cameraId, props.date] as const, () => {
  viewStart.value = 0
  cursorSeconds.value = typeof props.activeWallSeconds === 'number' ? props.activeWallSeconds : 12 * 3600
  motionEvents.value = []
  interaction.value = 'idle'
  hoverSeconds.value = null
  localRange.value = props.selectedRange ? normalizeTimelineRange(props.selectedRange.start, props.selectedRange.end, 1) : null
  void loadMotionEvents()
})

watch(() => props.activeWallSeconds, (value) => {
  if (interaction.value === 'playhead-drag') return
  if (typeof value !== 'number' || !Number.isFinite(value)) return
  cursorSeconds.value = Math.max(0, Math.min(86400, value))
  if (zoom.value !== '24h') centerOn(cursorSeconds.value)
})

watch(() => props.selectedRange, (value) => {
  if (interaction.value === 'range-start-drag' || interaction.value === 'range-end-drag' || interaction.value === 'range-move') return
  localRange.value = value ? normalizeTimelineRange(value.start, value.end, 1) : null
}, { deep: true })

watch(() => props.rangeSelectEnabled, (enabled) => {
  if (!enabled) {
    interaction.value = 'idle'
    hoverSeconds.value = null
  }
})

onMounted(() => void loadMotionEvents())
</script>

<template>
  <section class="playback-v3">
    <div class="playback-v3-toolbar">
      <div class="playback-v3-date">
        <strong>{{ date }}</strong>
        <span>{{ clockLabel(playheadSeconds, true) }}</span>
      </div>
      <div class="playback-v3-zoom" aria-label="时间轴缩放">
        <button v-for="level in zoomLevels" :key="level" type="button" :class="{ active: zoom === level }" @click="chooseZoom(level)">{{ level }}</button>
      </div>
    </div>

    <div class="playback-v3-stage">
      <div class="timeline-ruler" @wheel="handleWheel">
        <span v-for="tick in ticks" :key="`${tick.seconds}-${tick.ratio}`" :style="{ left: `${tick.ratio * 100}%` }">{{ tick.label }}</span>
      </div>

      <div class="timeline-lanes">
        <div class="timeline-lane-row recording-row">
          <div class="lane-label">录像</div>
          <div class="lane-track">
            <span v-for="block in recordingBlocks" :key="`recording-${block.item.id}`" class="recording-block" :style="{ left: `${block.left}%`, width: `${block.width}%` }" />
          </div>
        </div>
        <div class="timeline-lane-row motion-row">
          <div class="lane-label">移动</div>
          <div class="lane-track">
            <span v-for="block in motionBlocks" :key="`motion-${block.event.id}`" class="motion-block" :style="{ left: `${block.left}%`, width: `${Math.max(block.width, .28)}%` }" />
            <small v-if="motionError" class="lane-status">{{ motionError }}</small>
          </div>
        </div>
        <div class="timeline-lane-row disabled-row">
          <div class="lane-label">人员</div>
          <div class="lane-track"><small class="lane-status">未启用</small></div>
        </div>
        <div class="timeline-lane-row disabled-row">
          <div class="lane-label">车辆</div>
          <div class="lane-track"><small class="lane-status">未启用</small></div>
        </div>

        <div
          ref="overlayRef"
          class="timeline-track-overlay"
          :class="{ panning: interaction === 'pan', 'range-mode': rangeSelectEnabled }"
          @pointerdown="startPan"
          @pointermove="handlePointerMove"
          @pointerup="finishInteraction"
          @pointercancel="cancelInteraction"
          @pointerleave="clearHover"
          @click="seekAtPointer"
          @wheel="handleWheel"
        >
          <div v-if="hoverStyle && interaction === 'idle'" class="timeline-hover-preview" :style="hoverStyle" aria-hidden="true">
            <span>{{ clockLabel(hoverSeconds || 0, true) }}</span>
          </div>

          <div
            v-if="rangeSelectEnabled && selectionLayout && localRange"
            class="timeline-selection-band"
            :style="selectionStyle"
            @pointerdown.stop="startRangeMove"
          >
            <button
              type="button"
              class="timeline-range-handle start"
              :aria-label="`导出开始 ${clockLabel(localRange.start, true)}`"
              @pointerdown.stop="startRangeStartDrag"
            ><span>{{ clockLabel(localRange.start, true) }}</span></button>
            <button
              type="button"
              class="timeline-range-handle end"
              :aria-label="`导出结束 ${clockLabel(localRange.end, true)}`"
              @pointerdown.stop="startRangeEndDrag"
            ><span>{{ clockLabel(localRange.end, true) }}</span></button>
          </div>

          <div
            class="timeline-playhead"
            :class="{ gap: !playheadCovered, subdued: rangeSelectEnabled }"
            :style="playheadStyle"
            aria-hidden="true"
          ><span>{{ clockLabel(playheadSeconds, true) }}</span></div>
          <button
            v-if="!rangeSelectEnabled"
            type="button"
            class="timeline-playhead-hit"
            :style="playheadStyle"
            :aria-label="`拖动回放位置 ${clockLabel(playheadSeconds, true)}`"
            @pointerdown.stop="startPlayheadDrag"
          ></button>
        </div>
      </div>

      <div class="timeline-overview" @pointerdown="seekOverview">
        <span v-for="block in overviewBlocks" :key="`overview-${block.item.id}`" class="overview-recording" :style="{ left: `${block.left}%`, width: `${block.width}%` }" />
        <span v-if="overviewViewport" class="overview-window" :style="{ left: `${overviewViewport.left}%`, width: `${overviewViewport.width}%` }" />
      </div>
      <div class="overview-caption">
        <span>24h 概览</span>
        <span>{{ rangeSelectEnabled ? '拖动手柄调整导出范围 · 拖动选区整体移动' : '拖动游标定位 · 拖动背景平移 · 滚轮缩放' }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.playback-v3{--timeline-label-width:60px;border-top:1px solid var(--nvr-border);padding:14px 14px 10px;background:var(--nvr-surface);user-select:none}.playback-v3-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:8px}.playback-v3-date{display:flex;align-items:baseline;gap:12px;color:var(--nvr-text)}.playback-v3-date strong{font-size:14px}.playback-v3-date span{font-variant-numeric:tabular-nums;font-size:12px;color:var(--nvr-muted)}.playback-v3-zoom{display:flex;padding:2px;border:1px solid var(--nvr-border);border-radius:7px;background:var(--nvr-input)}.playback-v3-zoom button{border:0;background:transparent;color:var(--nvr-muted);font:inherit;font-size:12px;padding:5px 11px;border-radius:5px;cursor:pointer}.playback-v3-zoom button.active{background:var(--nvr-blue);color:#fff}.playback-v3-stage{position:relative}.timeline-ruler{position:relative;height:24px;margin-left:var(--timeline-label-width);border-bottom:1px solid var(--nvr-border)}.timeline-ruler span{position:absolute;top:5px;transform:translateX(-50%);font-size:10px;color:var(--nvr-subtle);font-variant-numeric:tabular-nums;white-space:nowrap}.timeline-lanes{position:relative}.timeline-lane-row{display:grid;grid-template-columns:var(--timeline-label-width) 1fr;min-height:28px;border-bottom:1px solid var(--nvr-border)}.lane-label{display:flex;align-items:center;padding-left:6px;font-size:11px;color:var(--nvr-muted)}.lane-track{position:relative;margin:6px 0;background:var(--nvr-input);overflow:hidden}.recording-block,.motion-block{position:absolute;top:0;bottom:0;border-radius:2px}.recording-block{background:linear-gradient(90deg,color-mix(in srgb,var(--nvr-blue) 82%,transparent),color-mix(in srgb,var(--nvr-blue) 58%,transparent))}.motion-block{background:var(--nvr-blue);box-shadow:0 0 0 1px var(--nvr-border-strong) inset}.disabled-row .lane-track{background:transparent}.lane-status{position:absolute;left:8px;top:50%;transform:translateY(-50%);font-size:10px;color:var(--nvr-subtle)}.timeline-track-overlay{position:absolute;z-index:4;left:var(--timeline-label-width);right:0;top:0;bottom:0;cursor:crosshair;touch-action:none}.timeline-track-overlay.panning{cursor:grabbing}.timeline-track-overlay.range-mode{cursor:grab}.timeline-hover-preview{position:absolute;z-index:5;top:0;bottom:0;width:1px;background:color-mix(in srgb,var(--nvr-text) 34%,transparent);pointer-events:none}.timeline-hover-preview span{position:absolute;top:-27px;left:50%;transform:translateX(-50%);padding:2px 5px;border:1px solid var(--nvr-border);border-radius:4px;background:var(--nvr-surface);color:var(--nvr-muted);font-size:10px;font-variant-numeric:tabular-nums;white-space:nowrap}.timeline-selection-band{position:absolute;z-index:6;top:1px;bottom:1px;box-sizing:border-box;border:1px solid color-mix(in srgb,var(--nvr-blue) 72%,var(--nvr-border));border-radius:4px;background:color-mix(in srgb,var(--nvr-blue) 18%,transparent);cursor:grab}.timeline-selection-band:active{cursor:grabbing}.timeline-range-handle{position:absolute;z-index:8;top:-1px;bottom:-1px;width:14px;padding:0;border:0;border-radius:4px;background:var(--nvr-blue);cursor:ew-resize;box-shadow:0 0 0 1px color-mix(in srgb,var(--nvr-blue) 30%,var(--nvr-border))}.timeline-range-handle.start{left:0;transform:translateX(-50%)}.timeline-range-handle.end{right:0;transform:translateX(50%)}.timeline-range-handle span{position:absolute;top:-28px;left:50%;transform:translateX(-50%);padding:3px 6px;border-radius:4px;background:var(--nvr-blue);color:#fff;font-size:10px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}.timeline-playhead{position:absolute;z-index:7;top:0;bottom:0;width:1px;background:var(--nvr-blue);box-shadow:0 0 0 1px color-mix(in srgb,var(--nvr-blue) 35%,transparent);pointer-events:none}.timeline-playhead.gap{background:var(--nvr-muted);box-shadow:none}.timeline-playhead.subdued{opacity:.5}.timeline-playhead span{position:absolute;top:-28px;left:50%;transform:translateX(-50%);padding:3px 6px;border-radius:4px;background:var(--nvr-blue);color:#fff;font-size:10px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}.timeline-playhead.gap span{background:var(--nvr-muted)}.timeline-playhead-hit{position:absolute;z-index:9;top:-2px;bottom:-2px;width:24px;transform:translateX(-50%);padding:0;border:0;background:transparent;cursor:ew-resize;touch-action:none}.timeline-playhead-hit:focus-visible{outline:2px solid var(--nvr-blue);outline-offset:1px}.timeline-overview{position:relative;height:18px;margin:10px 0 0 var(--timeline-label-width);border:1px solid var(--nvr-border);border-radius:4px;background:var(--nvr-input);overflow:hidden;cursor:pointer}.overview-recording{position:absolute;top:3px;bottom:3px;background:color-mix(in srgb,var(--nvr-muted) 46%,transparent)}.overview-window{position:absolute;top:0;bottom:0;border:1px solid var(--nvr-blue);background:color-mix(in srgb,var(--nvr-blue) 12%,transparent);box-sizing:border-box}.overview-caption{display:flex;justify-content:space-between;margin:5px 2px 0 var(--timeline-label-width);font-size:10px;color:var(--nvr-subtle)}
@media (max-width:900px){.playback-v3{--timeline-label-width:48px;padding-inline:8px}.playback-v3-zoom button{padding-inline:8px}}
</style>
