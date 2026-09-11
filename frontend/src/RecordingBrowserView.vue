<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

interface Camera {
  id: number
  name: string
  enabled: boolean
}

interface RecentRecording {
  id: number
  camera_id: number
  started_at?: string | null
}

interface PlaybackState {
  state: 'direct' | 'ready' | 'needed' | 'generating' | 'streaming' | 'error'
  direct: boolean
  error?: string | null
  video_codec?: string | null
  audio_codec?: string | null
  original_available?: boolean
  source_kind?: string
  remote_available?: boolean
  cloud_state?: 'ready' | 'downloading' | 'needed' | 'error' | string
  cloud_error?: string | null
  can_try_original?: boolean
}

interface RecordingItem {
  id: number
  camera_id: number
  started_at?: string | null
  ended_at?: string | null
  duration?: number | null
  file_size?: number | null
  video_codec?: string | null
  audio_codec?: string | null
  width?: number | null
  height?: number | null
  fps?: number | null
  status: string
  health_status: string
  upload_status: string
  warning_count: number
  filename: string
  playback: PlaybackState
}

interface BrowserResult {
  camera_id: number
  date: string
  timezone: string
  count: number
  total_duration: number
  total_size: number
  items: RecordingItem[]
}

interface CalendarDay {
  date: string
  count: number
  total_duration: number
  total_size: number
  remote_only: number
  warning_count: number
}

interface CalendarResult {
  camera_id: number
  month: string
  timezone: string
  days: CalendarDay[]
}

interface CalendarCell {
  key: string
  date?: string
  day?: number
  info?: CalendarDay
}

interface TimelineGap {
  key: string
  startSeconds: number
  endSeconds: number
  durationSeconds: number
  startLabel: string
  endLabel: string
  style: Record<string, string>
}

type PlaybackMode = '' | 'original' | 'proxy' | 'proxy-live'

const cameras = ref<Camera[]>([])
const selectedCamera = ref<number | null>(null)
const selectedDate = ref(todayString())
const calendarMonth = ref(todayString().slice(0, 7))
const latestRecording = ref<RecentRecording | null>(null)
const data = ref<BrowserResult | null>(null)
const calendarData = ref<CalendarResult | null>(null)
const loading = ref(false)
const calendarLoading = ref(false)
const playerVisible = ref(false)
const activeRecording = ref<RecordingItem | null>(null)
const videoSrc = ref('')
const preparing = ref(false)
const restoringCloud = ref(false)
const proxyError = ref('')
const playbackMode = ref<PlaybackMode>('')
const playbackNotice = ref('')
const fallbackInProgress = ref(false)
const autoAdvance = ref(true)

const recordings = computed(() => data.value?.items || [])
const calendarDayMap = computed(() => new Map((calendarData.value?.days || []).map((item) => [item.date, item])))
const calendarCells = computed<CalendarCell[]>(() => {
  const [year, month] = calendarMonth.value.split('-').map(Number)
  if (!year || !month) return []
  const firstWeekday = new Date(year, month - 1, 1).getDay()
  const daysInMonth = new Date(year, month, 0).getDate()
  const cells: CalendarCell[] = []
  for (let index = 0; index < firstWeekday; index += 1) {
    cells.push({ key: `blank-${index}` })
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    cells.push({ key: date, date, day, info: calendarDayMap.value.get(date) })
  }
  while (cells.length % 7 !== 0) cells.push({ key: `blank-tail-${cells.length}` })
  return cells
})
const playableRecordings = computed(() => recordings.value.filter(isPlayable))
const activeIndex = computed(() => recordings.value.findIndex((item) => item.id === activeRecording.value?.id))
const previousRecording = computed(() => {
  for (let index = activeIndex.value - 1; index >= 0; index -= 1) {
    if (isPlayable(recordings.value[index])) return recordings.value[index]
  }
  return null
})
const nextRecording = computed(() => {
  for (let index = activeIndex.value + 1; index < recordings.value.length; index += 1) {
    if (isPlayable(recordings.value[index])) return recordings.value[index]
  }
  return null
})
const activePlayablePosition = computed(() => {
  if (!activeRecording.value) return 0
  const index = playableRecordings.value.findIndex((item) => item.id === activeRecording.value?.id)
  return index >= 0 ? index + 1 : 0
})
const remoteOnlyCount = computed(() => recordings.value.filter((item) => !item.playback.original_available && item.playback.remote_available).length)
const timelineGaps = computed<TimelineGap[]>(() => {
  const result: TimelineGap[] = []
  let previousEnd: number | null = null

  for (const item of recordings.value) {
    const start = localSeconds(item.started_at)
    if (start === null) continue
    const explicitEnd = localSeconds(item.ended_at)
    const duration = Math.max(0, Number(item.duration || 0))
    const end = explicitEnd ?? Math.min(86400, start + duration)

    if (previousEnd !== null && start - previousEnd >= 5) {
      const gapStart = Math.max(0, previousEnd)
      const gapEnd = Math.min(86400, start)
      const gapDuration = gapEnd - gapStart
      const left = (gapStart / 86400) * 100
      const width = Math.max(0.15, (gapDuration / 86400) * 100)
      result.push({
        key: `${gapStart}-${gapEnd}`,
        startSeconds: gapStart,
        endSeconds: gapEnd,
        durationSeconds: gapDuration,
        startLabel: clockFromSeconds(gapStart),
        endLabel: clockFromSeconds(gapEnd),
        style: { left: `${left}%`, width: `${Math.min(width, 100 - left)}%` },
      })
    }
    previousEnd = previousEnd === null ? end : Math.max(previousEnd, end)
  }

  return result
})
const totalGapSeconds = computed(() => timelineGaps.value.reduce((sum, gap) => sum + gap.durationSeconds, 0))
const playbackModeLabel = computed(() => {
  if (playbackMode.value === 'proxy-live') return 'H.264 边转边播'
  if (playbackMode.value === 'proxy') return 'H.264 Proxy'
  if (playbackMode.value === 'original' && isHevc(activeRecording.value?.video_codec)) return 'HEVC 原片'
  if (playbackMode.value === 'original') return '原片直放'
  return ''
})
const playerLoadingText = computed(() => {
  if (restoringCloud.value) return '正在从 OpenList / 115 拉取云端录像…'
  if (playbackMode.value === 'proxy-live') return '正在启动 H.264 边转边播…'
  if (playbackMode.value === 'proxy') return '正在加载 H.264 Proxy…'
  return '正在加载原始录像…'
})

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function recordingDate(value?: string | null) {
  if (!value || value.length < 10) return null
  return value.slice(0, 10)
}

function codecName(value?: string | null) {
  return (value || '').toLowerCase()
}

function isH264(value?: string | null) {
  return ['h264', 'avc', 'avc1'].includes(codecName(value))
}

function isHevc(value?: string | null) {
  return ['hevc', 'h265', 'hvc1', 'hev1'].includes(codecName(value))
}

function isPlayable(item: RecordingItem) {
  return Boolean(
    item.playback?.original_available
    || item.playback?.remote_available
    || item.playback?.state === 'ready'
    || item.playback?.cloud_state === 'ready',
  )
}

function isCloudOnly(item: RecordingItem) {
  return !item.playback?.original_available && Boolean(item.playback?.remote_available)
}

function playbackButtonLabel(item: RecordingItem) {
  if (item.id === activeRecording.value?.id && playerVisible.value) return '播放中'
  if (isCloudOnly(item) && item.playback?.state !== 'ready') return '云端播放'
  return '播放'
}

function storageLabel(item: RecordingItem) {
  if (item.playback?.source_kind === 'cloud_cache') return '云端缓存'
  if (item.playback?.original_available) return '本地'
  if (item.playback?.remote_available) return '115归档'
  return '已清理'
}

function browserHevcHint() {
  if (typeof document === 'undefined') return 'unknown'
  const video = document.createElement('video')
  return video.canPlayType('video/mp4; codecs="hvc1"') || video.canPlayType('video/mp4; codecs="hev1"') || 'unsupported'
}

function goBack() {
  window.location.href = '/'
}

function localClock(value?: string | null) {
  if (!value) return '-'
  const match = value.match(/T(\d{2}:\d{2}:\d{2})/)
  return match?.[1] || value
}

function localSeconds(value?: string | null) {
  if (!value) return null
  const match = value.match(/T(\d{2}):(\d{2}):(\d{2})/)
  if (!match) return null
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3])
}

function clockFromSeconds(seconds: number) {
  const value = Math.max(0, Math.min(86400, Math.round(seconds)))
  const h = Math.floor(value / 3600)
  const m = Math.floor((value % 3600) / 60)
  const s = value % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function formatDuration(seconds?: number | null) {
  const value = Math.max(0, Math.round(seconds || 0))
  const h = Math.floor(value / 3600)
  const m = Math.floor((value % 3600) / 60)
  const s = value % 60
  if (h) return `${h}h ${m}m ${s}s`
  if (m) return `${m}m ${s}s`
  return `${s}s`
}

function formatCalendarDuration(seconds?: number | null) {
  const value = Math.max(0, Number(seconds || 0))
  if (value >= 3600) return `${(value / 3600).toFixed(value >= 36000 ? 0 : 1)}h`
  return `${Math.round(value / 60)}m`
}

function formatSize(bytes?: number | null) {
  const value = Number(bytes || 0)
  if (!value) return '-'
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}

function timelineStyle(item: RecordingItem) {
  const start = localSeconds(item.started_at)
  if (start === null) return { display: 'none' }
  const duration = Math.max(60, Number(item.duration || 0))
  const left = (start / 86400) * 100
  const width = Math.max(0.28, (duration / 86400) * 100)
  return { left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }
}

function healthType(value: string) {
  if (value === 'healthy') return 'success'
  if (value === 'unhealthy' || value === 'failed') return 'danger'
  return 'warning'
}

function recordingRowClassName({ row }: { row: RecordingItem }) {
  return row.id === activeRecording.value?.id ? 'playing-row' : ''
}

async function loadInitialSelection() {
  const [cameraResponse, recordingResponse] = await Promise.all([
    axios.get<Camera[]>('/api/cameras'),
    axios.get<RecentRecording[]>('/api/recordings?limit=1'),
  ])
  cameras.value = cameraResponse.data
  latestRecording.value = recordingResponse.data[0] || null

  const latest = latestRecording.value
  if (latest && cameras.value.some((camera) => camera.id === latest.camera_id)) {
    selectedCamera.value = latest.camera_id
    selectedDate.value = recordingDate(latest.started_at) || todayString()
  } else if (cameras.value.length) {
    selectedCamera.value = cameras.value[0].id
  }
  calendarMonth.value = selectedDate.value.slice(0, 7)
}

async function loadCalendar() {
  if (!selectedCamera.value || !calendarMonth.value) return
  calendarLoading.value = true
  try {
    const response = await axios.get<CalendarResult>('/api/recordings/calendar', {
      params: { camera_id: selectedCamera.value, month: calendarMonth.value },
    })
    calendarData.value = response.data
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '录像日历加载失败')
  } finally {
    calendarLoading.value = false
  }
}

async function loadRecordings() {
  if (!selectedCamera.value || !selectedDate.value) return
  loading.value = true
  try {
    const response = await axios.get<BrowserResult>('/api/recordings/browser', {
      params: { camera_id: selectedCamera.value, date: selectedDate.value },
    })
    data.value = response.data
    if (activeRecording.value) {
      const refreshed = response.data.items.find((item) => item.id === activeRecording.value?.id)
      if (refreshed) activeRecording.value = refreshed
    }
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '录像加载失败')
  } finally {
    loading.value = false
  }
}

async function handleCameraChange() {
  await Promise.all([loadRecordings(), loadCalendar()])
}

async function handleDateChange() {
  if (!selectedDate.value) return
  const month = selectedDate.value.slice(0, 7)
  if (calendarMonth.value !== month) {
    calendarMonth.value = month
    await Promise.all([loadRecordings(), loadCalendar()])
  } else {
    await loadRecordings()
  }
}

async function jumpToLatest() {
  const response = await axios.get<RecentRecording[]>('/api/recordings?limit=1')
  latestRecording.value = response.data[0] || null
  if (!latestRecording.value) {
    ElMessage.info('数据库里还没有录像记录')
    return
  }
  selectedCamera.value = latestRecording.value.camera_id
  selectedDate.value = recordingDate(latestRecording.value.started_at) || todayString()
  calendarMonth.value = selectedDate.value.slice(0, 7)
  await Promise.all([loadRecordings(), loadCalendar()])
}

async function changeDay(offset: number) {
  const current = new Date(`${selectedDate.value}T12:00:00`)
  current.setDate(current.getDate() + offset)
  selectedDate.value = `${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, '0')}-${String(current.getDate()).padStart(2, '0')}`
  const month = selectedDate.value.slice(0, 7)
  if (calendarMonth.value !== month) {
    calendarMonth.value = month
    await Promise.all([loadRecordings(), loadCalendar()])
  } else {
    await loadRecordings()
  }
}

async function shiftCalendarMonth(offset: number) {
  const [year, month] = calendarMonth.value.split('-').map(Number)
  const target = new Date(year, month - 1 + offset, 1)
  calendarMonth.value = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}`
  await loadCalendar()
}

async function selectCalendarDay(cell: CalendarCell) {
  if (!cell.date) return
  selectedDate.value = cell.date
  await loadRecordings()
}

function streamUrl(id: number, source: 'original' | 'proxy') {
  return `/api/recordings/${id}/stream?source=${source}&v=${Date.now()}`
}

function liveProxyUrl(id: number) {
  return `/api/recordings/${id}/proxy-live.mp4?v=${Date.now()}`
}

async function ensureCloudSource(item: RecordingItem) {
  restoringCloud.value = true
  playbackNotice.value = '本地录像已清理，正在从 OpenList / 115 拉取临时播放缓存…'
  try {
    let response = await axios.post<PlaybackState>(`/api/recordings/${item.id}/cloud-playback`)
    let state = response.data
    item.playback = { ...item.playback, ...state }
    if (state.original_available) return state
    if (state.cloud_state === 'error') throw new Error(state.cloud_error || '云端录像拉取失败')

    for (let attempt = 0; attempt < 900; attempt += 1) {
      if (!playerVisible.value || activeRecording.value?.id !== item.id) throw new Error('__cancelled__')
      await new Promise((resolve) => setTimeout(resolve, 1000))
      response = await axios.get<PlaybackState>(`/api/recordings/${item.id}/playback`)
      state = response.data
      item.playback = { ...item.playback, ...state }
      if (state.original_available) return state
      if (state.cloud_state === 'error') throw new Error(state.cloud_error || '云端录像拉取失败')
    }
    throw new Error('云端录像拉取超时')
  } finally {
    restoringCloud.value = false
  }
}

async function prepareProxy(item: RecordingItem, automaticFallback = false) {
  if (fallbackInProgress.value) return
  fallbackInProgress.value = true
  preparing.value = true
  proxyError.value = ''
  videoSrc.value = ''

  try {
    const response = await axios.get<PlaybackState>(`/api/recordings/${item.id}/playback`)
    const state = response.data
    item.playback = { ...item.playback, ...state }

    if (state.state === 'direct') {
      playbackMode.value = 'original'
      playbackNotice.value = '原片可直接播放，无需转码'
      videoSrc.value = streamUrl(item.id, 'original')
      await nextTick()
      return
    }

    if (state.state === 'ready') {
      playbackMode.value = 'proxy'
      playbackNotice.value = automaticFallback
        ? 'HEVC 原片解码失败，已切换已缓存的 H.264 Proxy'
        : '正在播放已缓存的 H.264 Proxy'
      videoSrc.value = streamUrl(item.id, 'proxy')
      await nextTick()
      return
    }

    playbackMode.value = 'proxy-live'
    playbackNotice.value = automaticFallback
      ? 'HEVC 原片解码失败，正在边转 H.264 边播放；完成后自动缓存'
      : '正在边转 H.264 边播放；无需等待整段转码完成'
    videoSrc.value = liveProxyUrl(item.id)
    await nextTick()
  } catch (error: any) {
    proxyError.value = error?.response?.data?.detail || error?.message || '播放准备失败'
    playbackNotice.value = ''
    ElMessage.error(proxyError.value)
  } finally {
    fallbackInProgress.value = false
  }
}

async function play(item: RecordingItem) {
  if (!isPlayable(item)) {
    ElMessage.warning('这段录像本地已清理且没有可用云端归档')
    return
  }

  activeRecording.value = item
  playerVisible.value = true
  videoSrc.value = ''
  proxyError.value = ''
  playbackNotice.value = ''
  fallbackInProgress.value = false
  restoringCloud.value = false
  preparing.value = true

  if (!item.playback.original_available && item.playback.state === 'ready') {
    playbackMode.value = 'proxy'
    playbackNotice.value = '本地原片已清理，直接播放已有 H.264 Proxy 缓存'
    videoSrc.value = streamUrl(item.id, 'proxy')
    await nextTick()
    return
  }

  if (!item.playback.original_available) {
    if (!item.playback.remote_available) {
      preparing.value = false
      proxyError.value = '本地原录像已清理，且没有成功归档记录'
      return
    }
    try {
      const state = await ensureCloudSource(item)
      if (!playerVisible.value || activeRecording.value?.id !== item.id) return
      item.playback = { ...item.playback, ...state }
      playbackNotice.value = '云端录像已拉回临时缓存，准备播放'
    } catch (error: any) {
      if (error?.message === '__cancelled__') return
      preparing.value = false
      proxyError.value = error?.response?.data?.detail || error?.message || '云端录像拉取失败'
      playbackNotice.value = ''
      ElMessage.error(proxyError.value)
      return
    }
  }

  if (isH264(item.video_codec) || isHevc(item.video_codec)) {
    playbackMode.value = 'original'
    if (isHevc(item.video_codec)) {
      const hint = browserHevcHint()
      playbackNotice.value = hint === 'unsupported'
        ? '优先尝试 HEVC 原片；浏览器失败会自动边转边播 H.264'
        : '优先尝试 HEVC 原片，失败会自动边转边播 H.264'
    } else {
      playbackNotice.value = item.playback.source_kind === 'cloud_cache'
        ? '云端录像临时缓存已就绪，H.264 原片直放'
        : 'H.264 原片直放，不转码'
    }
    videoSrc.value = streamUrl(item.id, 'original')
    await nextTick()
    return
  }

  await prepareProxy(item)
}

async function playPrevious() {
  if (previousRecording.value) await play(previousRecording.value)
}

async function playNext() {
  if (nextRecording.value) await play(nextRecording.value)
}

function handleVideoCanPlay() {
  preparing.value = false
  const cloudPrefix = activeRecording.value?.playback.source_kind === 'cloud_cache' ? '云端临时缓存 · ' : ''
  if (playbackMode.value === 'original' && isHevc(activeRecording.value?.video_codec)) {
    playbackNotice.value = `${cloudPrefix}浏览器已直接解码 HEVC 原片，无需转码`
  } else if (playbackMode.value === 'original') {
    playbackNotice.value = `${cloudPrefix}原片直放，无需转码`
  } else if (playbackMode.value === 'proxy-live') {
    playbackNotice.value = '正在边转边播 H.264；完整转码结束后会自动缓存，后续播放可直接拖动'
  } else if (playbackMode.value === 'proxy') {
    playbackNotice.value = '正在播放已缓存的 H.264 Proxy'
  }
}

async function handleVideoEnded() {
  if (autoAdvance.value && nextRecording.value) {
    playbackNotice.value = `当前片段播放完成，自动续播 ${localClock(nextRecording.value.started_at)}`
    await play(nextRecording.value)
    return
  }
  preparing.value = false
  playbackNotice.value = autoAdvance.value
    ? '已播放到当天最后一个可播放片段'
    : '当前片段播放完成，自动续播已关闭'
}

async function handleVideoError() {
  const item = activeRecording.value
  if (!playerVisible.value || !item) return
  if (playbackMode.value === 'original' && isHevc(item.video_codec) && !fallbackInProgress.value) {
    await prepareProxy(item, true)
    return
  }

  preparing.value = false
  if (!proxyError.value) {
    if (playbackMode.value === 'proxy-live') proxyError.value = 'H.264 边转边播启动或传输失败'
    else if (playbackMode.value === 'proxy') proxyError.value = 'H.264 Proxy 加载失败'
    else proxyError.value = '原始录像无法在当前浏览器中播放'
  }
}

function closePlayer() {
  videoSrc.value = ''
  playbackMode.value = ''
  playbackNotice.value = ''
  proxyError.value = ''
  preparing.value = false
  restoringCloud.value = false
  fallbackInProgress.value = false
}

onMounted(async () => {
  try {
    await loadInitialSelection()
    await Promise.all([loadRecordings(), loadCalendar()])
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '初始化失败')
  }
})
</script>

<template>
  <div class="page-shell">
    <div class="page-head">
      <div>
        <h2>录像浏览</h2>
        <p>连续回看 · 录像日历 · 本地优先 · OpenList / 115 云端归档回放</p>
      </div>
      <el-button @click="goBack">返回主界面</el-button>
    </div>

    <el-card shadow="never">
      <div class="filters">
        <el-select v-model="selectedCamera" placeholder="选择摄像头" filterable @change="handleCameraChange" style="width: 240px">
          <el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" />
        </el-select>
        <el-button @click="changeDay(-1)">前一天</el-button>
        <el-date-picker v-model="selectedDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" @change="handleDateChange" />
        <el-button @click="changeDay(1)">后一天</el-button>
        <el-button @click="jumpToLatest">最新录像</el-button>
        <el-button type="primary" :loading="loading" @click="loadRecordings">刷新</el-button>
      </div>

      <div v-if="data" class="summary">
        <span>{{ data.date }}</span>
        <span>{{ data.timezone }}</span>
        <span>{{ data.count }} 段录像</span>
        <span>总时长 {{ formatDuration(data.total_duration) }}</span>
        <span>总大小 {{ formatSize(data.total_size) }}</span>
        <span v-if="remoteOnlyCount" class="cloud-summary">仅云端 {{ remoteOnlyCount }} 段</span>
        <span :class="{ 'gap-summary-alert': timelineGaps.length > 0 }">缺口 {{ timelineGaps.length }} 处 / {{ formatDuration(totalGapSeconds) }}</span>
      </div>
    </el-card>

    <el-card shadow="never" class="section-gap" v-loading="calendarLoading">
      <template #header>
        <div class="calendar-head">
          <strong>录像日历 · {{ calendarMonth }}</strong>
          <div>
            <el-button size="small" @click="shiftCalendarMonth(-1)">上月</el-button>
            <el-button size="small" @click="shiftCalendarMonth(1)">下月</el-button>
          </div>
        </div>
      </template>
      <div class="calendar-weekdays">
        <span v-for="label in ['日', '一', '二', '三', '四', '五', '六']" :key="label">{{ label }}</span>
      </div>
      <div class="recording-calendar">
        <div v-for="cell in calendarCells" :key="cell.key" class="calendar-slot">
          <button
            v-if="cell.date"
            class="calendar-day"
            :class="{
              selected: cell.date === selectedDate,
              'has-recordings': !!cell.info,
              'warning-day': (cell.info?.warning_count || 0) > 0,
              'cloud-day': (cell.info?.remote_only || 0) > 0,
            }"
            @click="selectCalendarDay(cell)"
          >
            <span class="calendar-number">{{ cell.day }}</span>
            <template v-if="cell.info">
              <strong>{{ cell.info.count }} 段</strong>
              <span>{{ formatCalendarDuration(cell.info.total_duration) }}</span>
              <small v-if="cell.info.remote_only">云端 {{ cell.info.remote_only }}</small>
            </template>
            <span v-else class="no-recording">—</span>
          </button>
        </div>
      </div>
      <div class="calendar-legend">
        <span><i class="calendar-mark local-mark" />有录像</span>
        <span><i class="calendar-mark cloud-mark" />含云端归档</span>
        <span><i class="calendar-mark warning-mark" />含异常/警告</span>
      </div>
    </el-card>

    <el-card shadow="never" class="section-gap" v-loading="loading">
      <template #header><strong>24 小时时间轴</strong></template>
      <div class="axis-labels">
        <span v-for="hour in [0, 3, 6, 9, 12, 15, 18, 21, 24]" :key="hour">{{ String(hour).padStart(2, '0') }}:00</span>
      </div>
      <div class="timeline">
        <div class="grid-line" v-for="hour in [3, 6, 9, 12, 15, 18, 21]" :key="hour" :style="{ left: `${hour / 24 * 100}%` }" />
        <div v-for="gap in timelineGaps" :key="gap.key" class="gap-marker" :style="gap.style" :title="`录像缺口 ${gap.startLabel} ~ ${gap.endLabel} · ${formatDuration(gap.durationSeconds)}`" />
        <button
          v-for="item in recordings"
          :key="item.id"
          class="segment"
          :class="{
            unhealthy: item.health_status !== 'healthy',
            warning: item.health_status === 'healthy' && item.warning_count > 0,
            'cloud-only': isCloudOnly(item),
            deleted: !isPlayable(item),
            active: item.id === activeRecording?.id,
          }"
          :style="timelineStyle(item)"
          :disabled="!isPlayable(item)"
          :title="`${localClock(item.started_at)} · ${formatDuration(item.duration)} · ${storageLabel(item)} · ${item.health_status}`"
          @click="play(item)"
        />
      </div>
      <div class="legend">
        <span><i class="dot normal" />健康录像</span>
        <span><i class="dot warning-dot" />有警告</span>
        <span><i class="dot bad" />异常录像</span>
        <span><i class="dot cloud-dot" />仅云端归档</span>
        <span><i class="dot gap-dot" />录像缺口</span>
        <span><i class="dot deleted-dot" />不可播放</span>
        <span><i class="dot active-dot" />当前播放</span>
      </div>
    </el-card>

    <el-card shadow="never" class="section-gap">
      <template #header><strong>录像片段</strong></template>
      <el-table :data="recordings" stripe empty-text="当前摄像头在所选日期暂无录像" :row-class-name="recordingRowClassName">
        <el-table-column label="开始" width="110"><template #default="{ row }">{{ localClock(row.started_at) }}</template></el-table-column>
        <el-table-column label="时长" width="110"><template #default="{ row }">{{ formatDuration(row.duration) }}</template></el-table-column>
        <el-table-column label="大小" width="110"><template #default="{ row }">{{ formatSize(row.file_size) }}</template></el-table-column>
        <el-table-column label="视频" width="100"><template #default="{ row }">{{ row.video_codec || '-' }}</template></el-table-column>
        <el-table-column label="位置" width="110"><template #default="{ row }"><el-tag :type="isCloudOnly(row) ? 'warning' : row.playback.original_available ? 'success' : 'info'">{{ storageLabel(row) }}</el-tag></template></el-table-column>
        <el-table-column label="健康" width="100"><template #default="{ row }"><el-tag :type="healthType(row.health_status)">{{ row.health_status }}</el-tag></template></el-table-column>
        <el-table-column prop="upload_status" label="上传" width="110" />
        <el-table-column prop="filename" label="文件" min-width="240" show-overflow-tooltip />
        <el-table-column label="播放" width="125" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" :disabled="!isPlayable(row)" @click="play(row)">{{ playbackButtonLabel(row) }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="playerVisible" width="min(1000px, 92vw)" destroy-on-close title="录像回放" @closed="closePlayer">
      <div v-if="activeRecording" class="player-meta">
        <strong>{{ localClock(activeRecording.started_at) }}</strong>
        <span>{{ formatDuration(activeRecording.duration) }}</span>
        <span>{{ activeRecording.video_codec || '-' }}</span>
        <span>{{ activeRecording.width }}×{{ activeRecording.height }}</span>
        <span>{{ storageLabel(activeRecording) }}</span>
        <span v-if="activePlayablePosition">{{ activePlayablePosition }} / {{ playableRecordings.length }}</span>
        <el-tag v-if="playbackModeLabel" :type="playbackMode === 'proxy' || playbackMode === 'proxy-live' ? 'warning' : 'success'">{{ playbackModeLabel }}</el-tag>
      </div>

      <div class="player-controls">
        <div class="navigation-controls">
          <el-button :disabled="!previousRecording || preparing" @click="playPrevious">上一段</el-button>
          <el-button :disabled="!nextRecording || preparing" @click="playNext">下一段</el-button>
        </div>
        <label class="auto-advance-control"><span>播放结束自动续播</span><el-switch v-model="autoAdvance" /></label>
      </div>

      <div v-if="playbackNotice" class="playback-notice">{{ playbackNotice }}</div>
      <div class="player-box" v-loading="preparing" :element-loading-text="playerLoadingText">
        <video
          v-if="videoSrc"
          :src="videoSrc"
          controls
          autoplay
          playsinline
          preload="auto"
          @canplay="handleVideoCanPlay"
          @loadeddata="handleVideoCanPlay"
          @ended="handleVideoEnded"
          @error="handleVideoError"
        />
        <el-empty v-else-if="!preparing && proxyError" :description="proxyError" />
        <div v-else-if="preparing" class="prepare-note">
          {{ restoringCloud ? '云端录像只写入临时播放缓存，不会恢复到录像主目录。' : playbackMode === 'proxy-live' ? '首批 H.264 数据产生后即可播放，不需要等整段转码完成。' : playbackMode === 'proxy' ? '正在加载已经生成的 Proxy 缓存。' : '正在准备播放源。' }}
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
:global(body) { margin: 0; background: #f5f7fa; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.page-shell { max-width: 1500px; margin: 0 auto; padding: 24px; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.page-head h2 { margin: 0 0 6px; }
.page-head p { margin: 0; color: #909399; }
.filters { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.summary { display: flex; flex-wrap: wrap; gap: 22px; margin-top: 14px; color: #606266; font-size: 14px; }
.cloud-summary { color: #7c3aed; font-weight: 600; }
.gap-summary-alert { color: #e6a23c; font-weight: 600; }
.section-gap { margin-top: 16px; }
.calendar-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.calendar-weekdays, .recording-calendar { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 8px; }
.calendar-weekdays { margin-bottom: 8px; color: #909399; font-size: 12px; text-align: center; }
.calendar-slot { min-width: 0; }
.calendar-day { width: 100%; min-height: 82px; padding: 8px; border: 1px solid #ebeef5; border-radius: 7px; background: #fafafa; color: #606266; cursor: pointer; display: flex; flex-direction: column; align-items: flex-start; gap: 3px; text-align: left; }
.calendar-day:hover { border-color: #409eff; }
.calendar-day.has-recordings { background: #f0f9eb; border-color: #b3e19d; }
.calendar-day.cloud-day { box-shadow: inset 0 -3px 0 #7c3aed; }
.calendar-day.warning-day { border-color: #e6a23c; }
.calendar-day.selected { outline: 2px solid #409eff; outline-offset: 1px; }
.calendar-number { font-size: 12px; color: #909399; }
.calendar-day strong { color: #303133; font-size: 13px; }
.calendar-day small { color: #7c3aed; }
.no-recording { color: #c0c4cc; }
.calendar-legend { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 12px; font-size: 12px; color: #606266; }
.calendar-legend span { display: flex; align-items: center; gap: 6px; }
.calendar-mark { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.local-mark { background: #67c23a; }
.cloud-mark { background: #7c3aed; }
.warning-mark { background: #e6a23c; }
.axis-labels { display: flex; justify-content: space-between; color: #909399; font-size: 12px; margin-bottom: 8px; }
.timeline { position: relative; height: 74px; border: 1px solid #dcdfe6; border-radius: 6px; overflow: hidden; background: #fafafa; }
.grid-line { position: absolute; top: 0; bottom: 0; width: 1px; background: #ebeef5; }
.gap-marker { position: absolute; top: 0; bottom: 0; min-width: 2px; background: repeating-linear-gradient(135deg, rgba(230, 162, 60, .32) 0, rgba(230, 162, 60, .32) 5px, rgba(230, 162, 60, .08) 5px, rgba(230, 162, 60, .08) 10px); border-left: 1px solid rgba(230, 162, 60, .75); border-right: 1px solid rgba(230, 162, 60, .75); z-index: 1; }
.segment { position: absolute; top: 15px; height: 44px; border: 0; border-radius: 4px; background: #67c23a; cursor: pointer; min-width: 3px; opacity: .92; z-index: 2; transition: transform .12s ease, box-shadow .12s ease; }
.segment:hover:not(:disabled) { filter: brightness(.92); transform: translateY(-1px); }
.segment.warning { background: #e6a23c; }
.segment.unhealthy { background: #f56c6c; }
.segment.cloud-only { background: #7c3aed; }
.segment.deleted { background: #c0c4cc; cursor: not-allowed; }
.segment.active { box-shadow: 0 0 0 3px #409eff, 0 0 0 5px rgba(64, 158, 255, .22); transform: translateY(-2px); opacity: 1; }
.legend { display: flex; flex-wrap: wrap; gap: 20px; margin-top: 10px; color: #606266; font-size: 13px; }
.legend span { display: flex; align-items: center; gap: 6px; }
.dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.normal { background: #67c23a; }
.warning-dot { background: #e6a23c; }
.bad { background: #f56c6c; }
.cloud-dot { background: #7c3aed; }
.gap-dot { background: repeating-linear-gradient(135deg, #e6a23c 0, #e6a23c 3px, #fdf6ec 3px, #fdf6ec 6px); }
.deleted-dot { background: #c0c4cc; }
.active-dot { background: #409eff; box-shadow: 0 0 0 2px rgba(64, 158, 255, .22); }
:deep(.el-table .playing-row > td.el-table__cell) { background: #ecf5ff !important; }
.player-meta { display: flex; flex-wrap: wrap; gap: 18px; align-items: center; margin-bottom: 10px; color: #606266; }
.player-controls { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin: 8px 0 12px; }
.navigation-controls { display: flex; gap: 8px; }
.auto-advance-control { display: flex; align-items: center; gap: 10px; color: #606266; font-size: 13px; }
.playback-notice { margin-bottom: 12px; padding: 9px 12px; border-radius: 6px; background: #f4f4f5; color: #606266; font-size: 13px; }
.player-box { min-height: 360px; background: #111; display: flex; align-items: center; justify-content: center; border-radius: 6px; overflow: hidden; }
.player-box video { width: 100%; max-height: 70vh; background: #000; }
.prepare-note { color: #dcdfe6; padding: 30px; text-align: center; }
@media (max-width: 720px) {
  .page-shell { padding: 14px; }
  .page-head { align-items: flex-start; gap: 12px; }
  .calendar-weekdays, .recording-calendar { gap: 4px; }
  .calendar-day { min-height: 68px; padding: 5px; }
  .calendar-day span, .calendar-day strong, .calendar-day small { font-size: 10px; }
  .axis-labels span:nth-child(even) { display: none; }
  .player-controls { align-items: flex-start; flex-direction: column; }
}
</style>