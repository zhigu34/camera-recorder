<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'

import {
  ZOOM_SPANS,
  clampViewport,
  rangePercent,
  recordingRange,
  timeAtPointer,
  wallClockSeconds,
  zoomAround,
  type PlaybackZoom,
  type TimelineRecording,
} from './utils/playbackTimelineV3'

interface MotionEventItem {
  id: number
  started_at: string
  ended_at: string
}

const props = defineProps<{
  cameraId: number
  date: string
  recordings: TimelineRecording[]
  activeWallSeconds?: number | null
}>()

const emit = defineEmits<{
  seek: [seconds: number]
}>()

const zoom = ref<PlaybackZoom>('24h')
const viewStart = ref(0)
const motionEvents = ref<MotionEventItem[]>([])
const motionError = ref('')
const dragging = ref(false)
const dragStartX = ref(0)
const dragViewStart = ref(0)

const span = computed(() => ZOOM_SPANS[zoom.value])
const playheadSeconds = computed(() => viewStart.value + span.value / 2)
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

function chooseZoom(next: PlaybackZoom, anchorRatio = 0.5) {
  if (next === zoom.value) return
  const nextSpan = ZOOM_SPANS[next]
  viewStart.value = zoomAround(viewStart.value, span.value, nextSpan, anchorRatio)
  zoom.value = next
}

function pointerRatio(event: PointerEvent | WheelEvent, element: HTMLElement) {
  const rect = element.getBoundingClientRect()
  return rect.width ? Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) : 0.5
}

function seekAtPointer(event: PointerEvent) {
  if (dragging.value) return
  const element = event.currentTarget as HTMLElement
  emit('seek', timeAtPointer(viewStart.value, span.value, pointerRatio(event, element)))
}

function startDrag(event: PointerEvent) {
  if (span.value >= 86400) return
  dragging.value = true
  dragStartX.value = event.clientX
  dragViewStart.value = viewStart.value
  ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
}

function moveDrag(event: PointerEvent) {
  if (!dragging.value) return
  const element = event.currentTarget as HTMLElement
  const rect = element.getBoundingClientRect()
  if (!rect.width) return
  const deltaSeconds = ((dragStartX.value - event.clientX) / rect.width) * span.value
  viewStart.value = clampViewport(dragViewStart.value + deltaSeconds, span.value)
}

function endDrag() {
  dragging.value = false
}

function handleWheel(event: WheelEvent) {
  event.preventDefault()
  const element = event.currentTarget as HTMLElement
  const ratio = pointerRatio(event, element)
  const levels: PlaybackZoom[] = ['24h', '6h', '1h', '15m']
  const current = levels.indexOf(zoom.value)
  const next = event.deltaY < 0 ? Math.min(levels.length - 1, current + 1) : Math.max(0, current - 1)
  chooseZoom(levels[next], ratio)
}

function seekOverview(event: PointerEvent) {
  const element = event.currentTarget as HTMLElement
  centerOn(timeAtPointer(0, 86400, pointerRatio(event, element)))
}

async function loadMotionEvents() {
  motionError.value = ''
  try {
    const { data } = await axios.get<MotionEventItem[]>(`/api/motion/cameras/${props.cameraId}/events`, {
      params: { start: `${props.date}T00:00:00`, end: `${props.date}T23:59:59.999999`, limit: 1000 },
    })
    motionEvents.value = data
  } catch {
    motionEvents.value = []
    motionError.value = '移动事件加载失败'
  }
}

watch(() => [props.cameraId, props.date] as const, () => {
  viewStart.value = 0
  void loadMotionEvents()
})

watch(() => props.activeWallSeconds, (value) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || zoom.value === '24h') return
  const margin = span.value * 0.12
  if (value < viewStart.value + margin || value > viewStart.value + span.value - margin) centerOn(value)
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
        <button v-for="level in (Object.keys(ZOOM_SPANS) as PlaybackZoom[])" :key="level" type="button" :class="{ active: zoom === level }" @click="chooseZoom(level)">{{ level }}</button>
      </div>
    </div>

    <div class="playback-v3-stage" @wheel="handleWheel">
      <div class="timeline-ruler">
        <span v-for="tick in ticks" :key="`${tick.seconds}-${tick.ratio}`" :style="{ left: `${tick.ratio * 100}%` }">{{ tick.label }}</span>
      </div>

      <div class="timeline-lanes" :class="{ dragging }" @pointerdown="startDrag" @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="endDrag" @click="seekAtPointer">
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

        <div class="timeline-playhead" aria-hidden="true"><span>{{ clockLabel(playheadSeconds, true) }}</span></div>
      </div>

      <div class="timeline-overview" @pointerdown="seekOverview">
        <span v-for="block in overviewBlocks" :key="`overview-${block.item.id}`" class="overview-recording" :style="{ left: `${block.left}%`, width: `${block.width}%` }" />
        <span v-if="overviewViewport" class="overview-window" :style="{ left: `${overviewViewport.left}%`, width: `${overviewViewport.width}%` }" />
      </div>
      <div class="overview-caption"><span>24h 概览</span><span>拖动时间轴 · 滚轮缩放 · 点击定位</span></div>
    </div>
  </section>
</template>

<style scoped>
.playback-v3{border-top:1px solid var(--nvr-border);padding:14px 14px 10px;background:linear-gradient(180deg,rgba(10,14,19,.16),rgba(10,14,19,.42));user-select:none}.playback-v3-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:8px}.playback-v3-date{display:flex;align-items:baseline;gap:12px;color:var(--nvr-text)}.playback-v3-date strong{font-size:14px}.playback-v3-date span{font-variant-numeric:tabular-nums;font-size:12px;color:var(--nvr-muted)}.playback-v3-zoom{display:flex;padding:2px;border:1px solid var(--nvr-border);border-radius:7px;background:var(--nvr-input)}.playback-v3-zoom button{border:0;background:transparent;color:var(--nvr-muted);font:inherit;font-size:12px;padding:5px 11px;border-radius:5px;cursor:pointer}.playback-v3-zoom button.active{background:var(--nvr-blue);color:#fff}.playback-v3-stage{position:relative}.timeline-ruler{position:relative;height:24px;margin-left:60px;border-bottom:1px solid var(--nvr-border)}.timeline-ruler span{position:absolute;top:5px;transform:translateX(-50%);font-size:10px;color:var(--nvr-subtle);font-variant-numeric:tabular-nums;white-space:nowrap}.timeline-lanes{position:relative;cursor:crosshair}.timeline-lanes.dragging{cursor:grabbing}.timeline-lane-row{display:grid;grid-template-columns:60px 1fr;min-height:28px;border-bottom:1px solid rgba(255,255,255,.035)}.lane-label{display:flex;align-items:center;padding-left:6px;font-size:11px;color:var(--nvr-muted)}.lane-track{position:relative;margin:6px 0;background:rgba(255,255,255,.025);overflow:hidden}.recording-block,.motion-block{position:absolute;top:0;bottom:0;border-radius:2px}.recording-block{background:linear-gradient(90deg,rgba(76,141,255,.82),rgba(76,141,255,.58))}.motion-block{background:var(--nvr-blue);box-shadow:0 0 0 1px rgba(255,255,255,.08) inset}.disabled-row .lane-track{background:transparent}.lane-status{position:absolute;left:8px;top:50%;transform:translateY(-50%);font-size:10px;color:var(--nvr-subtle)}.timeline-playhead{position:absolute;left:calc(60px + (100% - 60px)/2);top:0;bottom:0;width:1px;background:#dce8ff;box-shadow:0 0 0 1px rgba(76,141,255,.35);pointer-events:none}.timeline-playhead span{position:absolute;top:-28px;left:50%;transform:translateX(-50%);padding:3px 6px;border-radius:4px;background:#b9d4ff;color:#10223d;font-size:10px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}.timeline-overview{position:relative;height:18px;margin:10px 0 0 60px;border:1px solid var(--nvr-border);border-radius:4px;background:rgba(255,255,255,.035);overflow:hidden;cursor:pointer}.overview-recording{position:absolute;top:3px;bottom:3px;background:rgba(130,149,176,.46)}.overview-window{position:absolute;top:0;bottom:0;border:1px solid var(--nvr-blue);background:rgba(76,141,255,.12);box-sizing:border-box}.overview-caption{display:flex;justify-content:space-between;margin:5px 2px 0 60px;font-size:10px;color:var(--nvr-subtle)}
@media (max-width:900px){.playback-v3{padding-inline:8px}.timeline-ruler,.timeline-overview,.overview-caption{margin-left:48px}.timeline-lane-row{grid-template-columns:48px 1fr}.timeline-playhead{left:calc(48px + (100% - 48px)/2)}.playback-v3-zoom button{padding-inline:8px}}
</style>
