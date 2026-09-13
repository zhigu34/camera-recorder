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
        <span>{{ feedEvents.length }} 个可回放事件</span>
      </div>
      <button type="button" class="event-refresh" :disabled="loading" @click="loadFeed">
        {{ loading ? '加载中' : '刷新' }}
      </button>
    </div>

    <div class="event-filter-row" aria-label="检测事件筛选">
      <button type="button" :class="{ active: filter === 'all' }" @click="filter = 'all'">全部</button>
      <button type="button" :class="{ active: filter === 'motion' }" @click="filter = 'motion'">移动</button>
      <button type="button" disabled title="人员识别尚未启用">人员</button>
      <button type="button" disabled title="车辆识别尚未启用">车辆</button>
    </div>

    <div class="event-feed-body">
      <div v-if="loading && !visibleEvents.length" class="event-feed-state">
        <span class="event-state-dot"></span>
        正在加载检测事件…
      </div>
      <div v-else-if="error" class="event-feed-state event-feed-error">{{ error }}</div>
      <div v-else-if="!visibleEvents.length" class="event-feed-state">
        <strong>暂无可回放检测事件</strong>
        <span>只有落在实际录像范围内的移动事件会显示在这里</span>
      </div>

      <button
        v-for="event in visibleEvents"
        :key="event.id"
        type="button"
        class="event-card"
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
            <small>移动</small>
          </div>
          <span class="event-time">{{ clockLabel(event.started_at) }}</span>
          <span class="event-kind">移动</span>
        </div>

        <div class="event-copy">
          <div class="event-copy-title">
            <strong>检测到移动</strong>
            <span>{{ durationLabel(event) }}</span>
          </div>
          <p>{{ motionEventZoneLabel(event, zones) }}</p>
          <small>点击从事件前 2 秒播放</small>
        </div>
        <span class="event-chevron">›</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.playback-event-feed{overflow:hidden;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface);color:var(--nvr-text)}
.event-feed-head{min-height:46px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 11px;border-bottom:1px solid var(--nvr-border)}
.event-feed-head>div{min-width:0;display:flex;align-items:baseline;gap:8px}.event-feed-head strong{font-size:12px}.event-feed-head span{color:var(--nvr-muted);font-size:9px}
.event-refresh{border:0;color:var(--nvr-blue);background:transparent;font:inherit;font-size:9px;cursor:pointer}.event-refresh:disabled{cursor:default;opacity:.55}
.event-filter-row{display:flex;gap:5px;padding:8px 10px;border-bottom:1px solid var(--nvr-border);background:color-mix(in srgb,var(--nvr-bg-soft) 48%,transparent)}
.event-filter-row button{min-width:48px;padding:5px 10px;border:1px solid var(--nvr-border);border-radius:999px;color:var(--nvr-muted);background:var(--nvr-input);font:inherit;font-size:9px;cursor:pointer;transition:border-color .12s ease,background .12s ease,color .12s ease}
.event-filter-row button.active{border-color:color-mix(in srgb,var(--nvr-blue) 56%,var(--nvr-border));color:#dceaff;background:color-mix(in srgb,var(--nvr-blue) 18%,var(--nvr-input))}.event-filter-row button:disabled{cursor:not-allowed;opacity:.42}
.event-feed-body{max-height:360px;overflow:auto;padding:7px;scrollbar-gutter:stable}.event-feed-state{min-height:118px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:14px;text-align:center;color:var(--nvr-subtle);font-size:9px}.event-feed-state strong{color:var(--nvr-muted);font-size:10px}.event-feed-error{color:var(--nvr-red)}
.event-state-dot{width:7px;height:7px;border-radius:50%;background:var(--nvr-blue);box-shadow:0 0 0 4px color-mix(in srgb,var(--nvr-blue) 15%,transparent)}
.event-card{position:relative;width:100%;display:grid;grid-template-columns:132px minmax(0,1fr) 12px;align-items:center;gap:10px;padding:7px;border:1px solid transparent;border-radius:8px;color:inherit;background:transparent;font:inherit;text-align:left;cursor:pointer;transition:background .12s ease,border-color .12s ease,transform .12s ease}.event-card+.event-card{margin-top:3px}.event-card:hover{border-color:var(--nvr-border);background:var(--nvr-bg-soft);transform:translateY(-1px)}.event-card.active{border-color:color-mix(in srgb,var(--nvr-blue) 62%,var(--nvr-border));background:color-mix(in srgb,var(--nvr-blue) 9%,var(--nvr-bg-soft))}
.event-thumb{position:relative;aspect-ratio:16/9;overflow:hidden;border:1px solid var(--nvr-border);border-radius:6px;background:#05090d}.event-thumb img{display:block;width:100%;height:100%;object-fit:cover}.event-thumb::after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,transparent 50%,rgba(0,0,0,.64))}.event-thumb-placeholder{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;color:#6f8298;background:radial-gradient(circle at 50% 45%,rgba(76,141,255,.14),transparent 45%),#070c12}.event-thumb-placeholder small{font-size:8px}.motion-glyph{width:17px;height:17px;border:2px solid color-mix(in srgb,var(--nvr-blue) 72%,#fff);border-radius:50%;box-shadow:0 0 0 5px color-mix(in srgb,var(--nvr-blue) 10%,transparent)}
.event-time,.event-kind{position:absolute;z-index:1;bottom:5px;font-size:8px}.event-time{left:6px;color:#fff;font-variant-numeric:tabular-nums}.event-kind{right:5px;padding:2px 5px;border-radius:999px;color:#dceaff;background:rgba(33,91,174,.78)}
.event-copy{min-width:0}.event-copy-title{display:flex;align-items:center;justify-content:space-between;gap:8px}.event-copy-title strong{overflow:hidden;color:var(--nvr-text-soft);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.event-copy-title span{flex:none;color:var(--nvr-muted);font-size:8px;font-variant-numeric:tabular-nums}.event-copy p{margin:5px 0 3px;overflow:hidden;color:var(--nvr-muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.event-copy small{color:var(--nvr-subtle);font-size:7px}.event-chevron{color:var(--nvr-subtle);font-size:18px;line-height:1}.event-card.active .event-chevron{color:var(--nvr-blue)}
@media (max-width:1220px){.event-card{grid-template-columns:112px minmax(0,1fr) 10px}.event-feed-body{max-height:310px}}
@media (max-width:760px){.event-card{grid-template-columns:104px minmax(0,1fr) 8px}.event-feed-body{max-height:none}}
</style>
