<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'

import {
  motionEventDuration,
  motionEventSeekTarget,
  motionEventSnapshotUrl,
  motionEventZoneLabel,
  prepareMotionEventFeed,
  type MotionFeedEvent,
  type MotionFeedZone,
} from './utils/motionEventFeed'
import { wallClockSeconds, type TimelineRecording } from './utils/playbackTimelineV3'

interface MotionDetectionResponse {
  zones?: MotionFeedZone[]
}

type EventFilter = 'all' | 'motion'

const props = defineProps<{
  cameraId: number
  date: string
  recordings: TimelineRecording[]
  activeWallSeconds?: number | null
}>()

const emit = defineEmits<{
  seek: [seconds: number]
}>()

const events = ref<MotionFeedEvent[]>([])
const zones = ref<MotionFeedZone[]>([])
const loading = ref(false)
const error = ref('')
const filter = ref<EventFilter>('all')
const brokenSnapshots = ref<Record<number, boolean>>({})

const feedEvents = computed(() => prepareMotionEventFeed(events.value, props.recordings))
const visibleEvents = computed(() => filter.value === 'motion' || filter.value === 'all' ? feedEvents.value : [])

function clockLabel(value?: string | null) {
  const seconds = wallClockSeconds(value)
  if (seconds === null) return '--:--:--'
  const safe = Math.max(0, Math.min(86399, Math.floor(seconds)))
  const hours = Math.floor(safe / 3600)
  const minutes = Math.floor((safe % 3600) / 60)
  const secs = safe % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function durationLabel(event: MotionFeedEvent) {
  const seconds = Math.max(1, Math.round(motionEventDuration(event)))
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60)
    const rest = seconds % 60
    return rest ? `${minutes}m ${rest}s` : `${minutes}m`
  }
  return `${seconds}s`
}

function snapshotAvailable(event: MotionFeedEvent) {
  return Boolean(event.snapshot_path) && !brokenSnapshots.value[event.id]
}

function markSnapshotBroken(eventId: number) {
  brokenSnapshots.value = { ...brokenSnapshots.value, [eventId]: true }
}

function isActive(event: MotionFeedEvent) {
  if (typeof props.activeWallSeconds !== 'number' || !Number.isFinite(props.activeWallSeconds)) return false
  const start = wallClockSeconds(event.started_at)
  const end = wallClockSeconds(event.ended_at)
  if (start === null || end === null) return false
  return props.activeWallSeconds >= Math.max(0, start - 2)
    && props.activeWallSeconds <= Math.max(start, end) + 1
}

function openEvent(event: MotionFeedEvent) {
  emit('seek', motionEventSeekTarget(event))
}

async function loadFeed() {
  loading.value = true
  error.value = ''
  brokenSnapshots.value = {}
  try {
    const [eventResult, settingsResult] = await Promise.allSettled([
      axios.get<MotionFeedEvent[]>('/api/motion-events', {
        params: {
          camera_id: props.cameraId,
          start: `${props.date}T00:00:00`,
          end: `${props.date}T23:59:59.999999`,
          limit: 1000,
        },
      }),
      axios.get<MotionDetectionResponse>(`/api/cameras/${props.cameraId}/motion-detection`),
    ])

    if (eventResult.status === 'rejected') throw eventResult.reason
    events.value = eventResult.value.data
    zones.value = settingsResult.status === 'fulfilled' ? settingsResult.value.data.zones || [] : []
  } catch {
    events.value = []
    zones.value = []
    error.value = '检测事件加载失败'
  } finally {
    loading.value = false
  }
}

watch(() => [props.cameraId, props.date] as const, () => {
  events.value = []
  zones.value = []
  void loadFeed()
})

onMounted(() => void loadFeed())
</script>

<template>
  <section class="playback-event-feed">
    <div class="event-feed-head">
      <div>
        <strong>检测事件</strong>
        <span>{{ feedEvents.length }}</span>
      </div>
      <button type="button" class="event-refresh" :disabled="loading" @click="loadFeed">
        {{ loading ? '加载中' : '刷新' }}
      </button>
    </div>

    <div class="event-filter-row" aria-label="检测事件筛选">
      <button type="button" :class="{ active: filter === 'all' }" @click="filter = 'all'">全部</button>
      <button type="button" :class="{ active: filter === 'motion' }" @click="filter = 'motion'">移动</button>
    </div>

    <div class="event-feed-body">
      <div v-if="loading && !visibleEvents.length" class="event-feed-state">
        <span class="event-state-dot"></span>
        正在加载检测事件…
      </div>
      <div v-else-if="error" class="event-feed-state event-feed-error">{{ error }}</div>
      <div v-else-if="!visibleEvents.length" class="event-feed-state">
        <strong>暂无检测事件</strong>
        <span>当前录像范围内没有移动检测</span>
      </div>

      <button
        v-for="event in visibleEvents"
        :key="event.id"
        type="button"
        class="event-row"
        :class="{ active: isActive(event) }"
        @click="openEvent(event)"
      >
        <div class="event-thumb">
          <img
            v-if="snapshotAvailable(event)"
            :src="motionEventSnapshotUrl(event)"
            alt="移动检测事件截图"
            loading="lazy"
            @error="markSnapshotBroken(event.id)"
          />
          <div v-else class="event-thumb-placeholder">
            <span class="motion-glyph"></span>
          </div>
          <span class="event-time">{{ clockLabel(event.started_at) }}</span>
        </div>

        <div class="event-meta">
          <div class="event-primary">
            <strong><span class="motion-dot"></span>移动</strong>
            <time>{{ durationLabel(event) }}</time>
          </div>
          <div class="event-secondary">
            <span>{{ motionEventZoneLabel(event, zones) }}</span>
          </div>
        </div>
        <span class="event-active-mark" aria-hidden="true"></span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.playback-event-feed{min-height:0;display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface);color:var(--nvr-text)}
.event-feed-head{flex:none;min-height:42px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:7px 10px;border-bottom:1px solid color-mix(in srgb,var(--nvr-border) 70%,transparent)}.event-feed-head>div{display:flex;align-items:center;gap:7px}.event-feed-head strong{font-size:11px}.event-feed-head span{min-width:18px;padding:2px 5px;border-radius:999px;color:var(--nvr-subtle);background:var(--nvr-input);font-size:8px;text-align:center}.event-refresh{border:0;color:var(--nvr-blue);background:transparent;font:inherit;font-size:9px;cursor:pointer}.event-refresh:disabled{opacity:.5;cursor:default}
.event-filter-row{flex:none;display:flex;gap:3px;padding:6px 8px;border-bottom:1px solid color-mix(in srgb,var(--nvr-border) 58%,transparent)}.event-filter-row button{height:24px;padding:0 9px;border:0;border-radius:6px;color:var(--nvr-subtle);background:transparent;font:inherit;font-size:9px;cursor:pointer}.event-filter-row button:hover{color:var(--nvr-text-soft);background:var(--nvr-hover)}.event-filter-row button.active{color:var(--nvr-text);background:color-mix(in srgb,var(--nvr-blue) 11%,var(--nvr-input))}
.event-feed-body{min-height:0;flex:1;overflow:auto;padding:4px 5px 7px;scrollbar-gutter:stable;overscroll-behavior:contain}.event-feed-state{min-height:118px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:14px;text-align:center;color:var(--nvr-subtle);font-size:9px}.event-feed-state strong{color:var(--nvr-muted);font-size:10px}.event-feed-error{color:var(--nvr-red)}.event-state-dot{width:6px;height:6px;border-radius:50%;background:var(--nvr-blue);box-shadow:0 0 0 4px color-mix(in srgb,var(--nvr-blue) 13%,transparent)}
.event-row{position:relative;width:100%;display:grid;grid-template-columns:94px minmax(0,1fr) 2px;align-items:center;gap:8px;padding:5px;border:0;border-radius:7px;color:inherit;background:transparent;font:inherit;text-align:left;cursor:pointer;transition:background .12s ease}.event-row+.event-row{margin-top:2px}.event-row:hover{background:var(--nvr-hover)}.event-row.active{background:color-mix(in srgb,var(--nvr-blue) 8%,var(--nvr-hover))}.event-active-mark{align-self:stretch;width:2px;border-radius:2px;background:transparent}.event-row.active .event-active-mark{background:var(--nvr-blue)}
.event-thumb{position:relative;aspect-ratio:16/9;overflow:hidden;border-radius:5px;background:#05090d}.event-thumb img{display:block;width:100%;height:100%;object-fit:cover}.event-thumb::after{content:'';position:absolute;inset:46% 0 0;background:linear-gradient(180deg,transparent,rgba(0,0,0,.64))}.event-thumb-placeholder{position:absolute;inset:0;display:grid;place-items:center;background:radial-gradient(circle at 50% 45%,rgba(76,141,255,.12),transparent 42%),#070c12}.motion-glyph{width:15px;height:15px;border:1.5px solid color-mix(in srgb,var(--nvr-blue) 72%,#fff);border-radius:50%;box-shadow:0 0 0 4px color-mix(in srgb,var(--nvr-blue) 9%,transparent)}.event-time{position:absolute;z-index:1;left:5px;bottom:4px;color:#f5f8fb;font-size:7.5px;font-variant-numeric:tabular-nums}
.event-meta{min-width:0;display:grid;gap:5px}.event-primary{display:flex;align-items:center;justify-content:space-between;gap:7px}.event-primary strong{min-width:0;display:flex;align-items:center;gap:5px;color:var(--nvr-text-soft);font-size:9.5px;font-weight:650}.motion-dot{width:5px;height:5px;flex:none;border-radius:50%;background:var(--nvr-blue)}.event-primary time{flex:none;color:var(--nvr-subtle);font-size:8px;font-variant-numeric:tabular-nums}.event-secondary{min-width:0;color:var(--nvr-muted);font-size:8.5px}.event-secondary span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.event-row:focus-visible{outline:2px solid color-mix(in srgb,var(--nvr-blue) 58%,transparent);outline-offset:-2px}@media(max-width:760px){.event-row{grid-template-columns:108px minmax(0,1fr) 2px}}
</style>
