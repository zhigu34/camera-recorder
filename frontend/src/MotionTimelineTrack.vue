<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { clockSeconds, dayQueryRange, timelineRange } from './utils/motionTimeline'

interface MotionEventItem {
  id: number
  camera_id: number
  zone_id?: number | null
  recording_id?: number | null
  started_at: string
  ended_at: string
  peak_score?: number | null
  snapshot_path?: string | null
}

interface MotionZoneItem {
  id: number
  name: string
  enabled: boolean
}

interface MotionSettingsResponse {
  zones?: MotionZoneItem[]
}

const props = defineProps<{
  cameraId: number
  date: string
}>()

const emit = defineEmits<{
  (event: 'select', item: MotionEventItem): void
}>()

const loading = ref(false)
const events = ref<MotionEventItem[]>([])
const zones = ref<MotionZoneItem[]>([])
let requestSerial = 0

const zoneNames = computed(() => new Map(zones.value.map((zone) => [zone.id, zone.name])))
const positionedEvents = computed(() => events.value.flatMap((item) => {
  const start = clockSeconds(item.started_at)
  const end = clockSeconds(item.ended_at)
  if (start === null || end === null) return []
  const range = timelineRange(start, Math.max(end, start + 0.25), 0, 86400)
  if (!range) return []
  return [{ item, range }]
}))

function localClock(value: string) {
  const match = value.match(/T(\d{2}:\d{2}:\d{2})/)
  return match?.[1] || value
}

function durationLabel(item: MotionEventItem) {
  const start = Date.parse(item.started_at)
  const end = Date.parse(item.ended_at)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '-'
  const seconds = Math.max(0, (end - start) / 1000)
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`
}

function zoneLabel(item: MotionEventItem) {
  return item.zone_id ? zoneNames.value.get(item.zone_id) || `区域 #${item.zone_id}` : '全画面'
}

function eventTitle(item: MotionEventItem) {
  return `移动 · ${zoneLabel(item)} · ${localClock(item.started_at)}–${localClock(item.ended_at)} · ${durationLabel(item)}`
}

async function load() {
  const serial = ++requestSerial
  if (!props.cameraId || !props.date) {
    events.value = []
    zones.value = []
    return
  }
  loading.value = true
  const range = dayQueryRange(props.date)
  try {
    const [eventResponse, settingsResponse] = await Promise.all([
      axios.get<MotionEventItem[]>('/api/motion-events', {
        params: { camera_id: props.cameraId, start: range.start, end: range.end, limit: 1000 },
      }),
      axios.get<MotionSettingsResponse>(`/api/cameras/${props.cameraId}/motion-detection`),
    ])
    if (serial !== requestSerial) return
    events.value = eventResponse.data
    zones.value = settingsResponse.data.zones || []
  } catch {
    if (serial !== requestSerial) return
    events.value = []
    zones.value = []
  } finally {
    if (serial === requestSerial) loading.value = false
  }
}

watch(() => [props.cameraId, props.date] as const, () => void load(), { immediate: true })
</script>

<template>
  <div class="motion-timeline-track" :class="{ loading }">
    <div class="motion-track-head">
      <div><span class="motion-track-dot"></span><strong>移动</strong><span>{{ events.length }} 个事件</span></div>
      <small>点击事件跳到发生前 2 秒</small>
    </div>
    <div class="motion-track-lane" :aria-label="`${date} 移动事件轨道`">
      <span v-for="hour in 23" :key="hour" class="motion-hour-line" :style="{ left: `${hour / 24 * 100}%` }" aria-hidden="true"></span>
      <button
        v-for="entry in positionedEvents"
        :key="entry.item.id"
        type="button"
        class="motion-event-mark"
        :class="{ unlinked: !entry.item.recording_id }"
        :style="{ left: `${entry.range.left}%`, width: `${entry.range.width}%` }"
        :title="eventTitle(entry.item)"
        :aria-label="eventTitle(entry.item)"
        @click="emit('select', entry.item)"
      ></button>
      <span v-if="!loading && !events.length" class="motion-track-empty">当天暂无移动事件</span>
    </div>
    <div class="motion-track-axis" aria-hidden="true"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div>
  </div>
</template>

<style scoped>
.motion-timeline-track{margin-top:10px;padding-top:10px;border-top:1px solid color-mix(in srgb,var(--nvr-border) 82%,transparent)}
.motion-track-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:7px}.motion-track-head>div{display:flex;align-items:center;gap:6px}.motion-track-head strong{font-size:10px}.motion-track-head span,.motion-track-head small{color:var(--nvr-subtle);font-size:8px}.motion-track-dot{width:6px;height:6px;border-radius:50%;background:var(--nvr-blue);box-shadow:0 0 0 3px color-mix(in srgb,var(--nvr-blue) 14%,transparent)}
.motion-track-lane{position:relative;height:24px;overflow:hidden;border:1px solid var(--nvr-border);border-radius:5px;background:color-mix(in srgb,var(--nvr-bg) 80%,#000)}.motion-hour-line{position:absolute;top:0;bottom:0;width:1px;background:color-mix(in srgb,var(--nvr-border) 55%,transparent);pointer-events:none}.motion-event-mark{position:absolute;top:5px;height:12px;min-width:3px;padding:0;border:0;border-radius:3px;background:var(--nvr-blue);box-shadow:0 0 0 1px color-mix(in srgb,var(--nvr-blue) 30%,transparent);cursor:pointer;transition:filter .12s ease,transform .12s ease,box-shadow .12s ease}.motion-event-mark:hover,.motion-event-mark:focus-visible{z-index:2;filter:brightness(1.2);transform:scaleY(1.18);box-shadow:0 0 0 2px color-mix(in srgb,var(--nvr-blue) 30%,transparent)}.motion-event-mark.unlinked{opacity:.55}.motion-track-empty{position:absolute;inset:0;display:grid;place-items:center;color:var(--nvr-subtle);font-size:8px;pointer-events:none}.motion-track-axis{display:flex;justify-content:space-between;margin-top:4px;color:var(--nvr-subtle);font-size:7px}.motion-timeline-track.loading{opacity:.72}
</style>
