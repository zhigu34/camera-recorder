<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import {
  PlaybackAttemptTracker,
  hevcSupportHint,
  isBrowserSafeAudio,
} from './utils/playbackCompatibility'

interface Camera { id: number; name: string; enabled: boolean }
interface RecentRecording { id: number; camera_id: number; started_at?: string | null }
interface ProxyProgress {
  mode?: 'live' | 'generate' | string
  elapsed_seconds?: number
  duration_seconds?: number
  source_offset_seconds?: number
  percent?: number | null
  running_seconds?: number
  cancellable?: boolean
}
interface PlaybackState {
  state: 'direct' | 'ready' | 'needed' | 'generating' | 'streaming' | 'error'
  direct: boolean
  error?: string | null
  progress?: ProxyProgress | null
  video_codec?: string | null
  audio_codec?: string | null
  original_available?: boolean
  source_kind?: string
  remote_available?: boolean
  cloud_state?: string
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
  camera_id: number; date: string; timezone: string; count: number
  total_duration: number; total_size: number; items: RecordingItem[]
}
interface CalendarDay {
  date: string; count: number; total_duration: number; total_size: number
  remote_only: number; warning_count: number
}
interface CalendarResult { camera_id: number; month: string; timezone: string; days: CalendarDay[] }
interface CalendarCell { key: string; date?: string; day?: number; info?: CalendarDay }
interface TimelineGap {
  key: string; durationSeconds: number; startLabel: string; endLabel: string
  style: Record<string, string>
}
interface AdjacentResult { direction: 'previous' | 'next'; date?: string | null; item?: RecordingItem | null }

type PlaybackMode = '' | 'original' | 'proxy' | 'proxy-live'
type ActivePlaybackMode = Exclude<PlaybackMode, ''>
type AdjacentDirection = 'previous' | 'next'

const MAX_ORIGINAL_RECOVERY_ATTEMPTS = 2

const cameras = ref<Camera[]>([])
const selectedCamera = ref<number | null>(null)
const selectedDate = ref(todayString())
const calendarMonth = ref(todayString().slice(0, 7))
const latestRecording = ref<RecentRecording | null>(null)
const data = ref<BrowserResult | null>(null)
const calendarData = ref<CalendarResult | null>(null)
const loading = ref(false)
const calendarLoading = ref(false)
const navigationLoading = ref(false)
const playerVisible = ref(false)
const activeRecording = ref<RecordingItem | null>(null)
const videoSrc = ref('')
const preparing = ref(false)
const proxyError = ref('')
const playbackMode = ref<PlaybackMode>('')
const playbackNotice = ref('')
const fallbackInProgress = ref(false)
const autoAdvance = ref(true)
const proxyProgress = ref<ProxyProgress | null>(null)
const cancellingProxy = ref(false)
const browserHevcHint = ref(hevcSupportHint())
const originalPlaybackConfirmed = ref(false)
const recoveringOriginal = ref(false)
const originalRecoveryAttempts = ref(0)
const pendingOriginalSeek = ref<number | null>(null)
const pendingCompatibilitySeek = ref<number | null>(null)
const compatibilityResumeAt = ref(0)
const originalRecoveryPoint = ref(0)
const lastPlaybackTime = ref(0)
const playbackTracker = new PlaybackAttemptTracker()
let progressTimer: number | null = null

const recordings = computed(() => data.value?.items || [])
const playableRecordings = computed(() => recordings.value.filter(isPlayable))
const activeIndex = computed(() => recordings.value.findIndex((item) => item.id === activeRecording.value?.id))
const previousRecording = computed(() => findLocalAdjacent(-1))
const nextRecording = computed(() => findLocalAdjacent(1))
const activePlayablePosition = computed(() => {
  if (!activeRecording.value) return 0
  const index = playableRecordings.value.findIndex((item) => item.id === activeRecording.value?.id)
  return index >= 0 ? index + 1 : 0
})
const remoteOnlyCount = computed(() => recordings.value.filter(isCloudOnly).length)
const calendarDayMap = computed(() => new Map((calendarData.value?.days || []).map((item) => [item.date, item])))
const calendarCells = computed<CalendarCell[]>(() => {
  const [year, month] = calendarMonth.value.split('-').map(Number)
  if (!year || !month) return []
  const cells: CalendarCell[] = []
  const firstWeekday = new Date(year, month - 1, 1).getDay()
  const daysInMonth = new Date(year, month, 0).getDate()
  for (let index = 0; index < firstWeekday; index += 1) cells.push({ key: `blank-${index}` })
  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    cells.push({ key: date, date, day, info: calendarDayMap.value.get(date) })
  }
  while (cells.length % 7 !== 0) cells.push({ key: `blank-tail-${cells.length}` })
  return cells
})
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
  if (playbackMode.value === 'proxy-live') return 'H.264 1080p 兼容流'
  if (playbackMode.value === 'proxy') return 'H.264 1080p 兼容缓存'
  if (playbackMode.value === 'original' && isHevc(activeRecording.value?.video_codec)) return 'HEVC 原片'
  if (playbackMode.value === 'original') return '原片直放'
  return ''
})
const effectiveProgressPercent = computed(() => {
  const progress = proxyProgress.value
  if (!progress) return 0
  if (typeof progress.percent === 'number') return Math.max(0, Math.min(100, progress.percent))
  const duration = Number(activeRecording.value?.duration || progress.duration_seconds || 0)
  const elapsed = Number(progress.elapsed_seconds || 0)
  if (!duration) return 0
  return Math.max(0, Math.min(100, Number((elapsed / duration * 100).toFixed(1))))
})
const proxyProgressText = computed(() => {
  const progress = proxyProgress.value
  if (!progress) return ''
  const elapsed = formatDuration(progress.elapsed_seconds)
  const total = formatDuration(activeRecording.value?.duration || progress.duration_seconds)
  const runtime = progress.running_seconds ? ` · 已运行 ${formatDuration(progress.running_seconds)}` : ''
  return `已转至原片 ${elapsed} / ${total}${runtime}`
})
const showProxyProgress = computed(() =>
  playbackMode.value === 'proxy-live' && Boolean(proxyProgress.value),
)
const playerLoadingText = computed(() => {
  if (navigationLoading.value) return '正在定位相邻录像…'
  if (recoveringOriginal.value) return '正在恢复原片播放…'
  if (playbackMode.value === 'proxy-live') return compatibilityResumeAt.value > 0 ? `正在从 ${formatDuration(compatibilityResumeAt.value)} 启动 H.264 兼容流…` : '正在启动 H.264 兼容流…'
  if (playbackMode.value === 'proxy') return compatibilityResumeAt.value > 0 ? `正在从 ${formatDuration(compatibilityResumeAt.value)} 加载 H.264 兼容缓存…` : '正在加载 H.264 兼容缓存…'
  if (activeRecording.value && isCloudOnly(activeRecording.value)) return '正在连接 OpenList 云端流…'
  return '正在加载原始录像…'
})

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
function recordingDate(value?: string | null) { return value && value.length >= 10 ? value.slice(0, 10) : null }
function codecName(value?: string | null) { return (value || '').toLowerCase() }
function isH264(value?: string | null) { return ['h264', 'avc', 'avc1'].includes(codecName(value)) }
function isHevc(value?: string | null) { return ['hevc', 'h265', 'hvc1', 'hev1'].includes(codecName(value)) }
function isPlayable(item: RecordingItem) {
  return Boolean(item.playback?.original_available || item.playback?.remote_available || item.playback?.state === 'ready' || item.playback?.cloud_state === 'ready')
}
function isCloudOnly(item: RecordingItem) { return !item.playback?.original_available && Boolean(item.playback?.remote_available) }
function storageLabel(item: RecordingItem) {
  if (item.playback?.source_kind === 'openlist_stream') return 'OpenList直连'
  if (item.playback?.source_kind === 'cloud_cache') return '云端缓存'
  if (item.playback?.original_available) return '本地'
  if (item.playback?.remote_available) return 'OpenList归档'
  return '已清理'
}
function playbackButtonLabel(item: RecordingItem) {
  if (item.id === activeRecording.value?.id && playerVisible.value) return '播放中'
  return isCloudOnly(item) && item.playback.state !== 'ready' ? '云端播放' : '播放'
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
  const h = Math.floor(value / 3600); const m = Math.floor((value % 3600) / 60); const s = value % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
function formatDuration(seconds?: number | null) {
  const value = Math.max(0, Math.round(seconds || 0)); const h = Math.floor(value / 3600); const m = Math.floor((value % 3600) / 60); const s = value % 60
  if (h) return `${h}h ${m}m ${s}s`; if (m) return `${m}m ${s}s`; return `${s}s`
}
function formatCalendarDuration(seconds?: number | null) {
  const value = Math.max(0, Number(seconds || 0)); return value >= 3600 ? `${(value / 3600).toFixed(value >= 36000 ? 0 : 1)}h` : `${Math.round(value / 60)}m`
}
function formatSize(bytes?: number | null) {
  const value = Number(bytes || 0); if (!value) return '-'; return value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(2)} GB` : `${(value / 1024 ** 2).toFixed(1)} MB`
}
function timelineStyle(item: RecordingItem) {
  const start = localSeconds(item.started_at); if (start === null) return { display: 'none' }
  const duration = Math.max(60, Number(item.duration || 0)); const left = start / 86400 * 100; const width = Math.max(0.28, duration / 86400 * 100)
  return { left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }
}
function healthType(value: string) { return value === 'healthy' ? 'success' : value === 'unhealthy' || value === 'failed' ? 'danger' : 'warning' }
function recordingRowClassName({ row }: { row: RecordingItem }) { return row.id === activeRecording.value?.id ? 'playing-row' : '' }
function findLocalAdjacent(step: -1 | 1) {
  for (let index = activeIndex.value + step; index >= 0 && index < recordings.value.length; index += step) if (isPlayable(recordings.value[index])) return recordings.value[index]
  return null
}
function streamUrl(id: number, source: 'original' | 'proxy') { return `/api/recordings/${id}/stream?source=${source}&v=${Date.now()}` }
function liveProxyUrl(id: number, startSeconds = 0) {
  const start = Math.max(0, Number(startSeconds || 0))
  return `/api/recordings/${id}/proxy-live.mp4?v=${Date.now()}&start_seconds=${encodeURIComponent(start.toFixed(3))}`
}
function metricSourceKind(item: RecordingItem, mode: ActivePlaybackMode) {
  if (mode === 'proxy') return 'proxy_cache'
  if (item.playback?.source_kind) return item.playback.source_kind
  return isCloudOnly(item) ? 'openlist_stream' : 'local'
}
function resetOriginalRecovery() {
  recoveringOriginal.value = false
  originalRecoveryAttempts.value = 0
  pendingOriginalSeek.value = null
  originalRecoveryPoint.value = 0
  lastPlaybackTime.value = 0
}
function resetCompatibilityResume() {
  pendingCompatibilitySeek.value = null
  compatibilityResumeAt.value = 0
}
function beginPlaybackSource(item: RecordingItem, mode: ActivePlaybackMode, src: string, notice: string) {
  playbackMode.value = mode
  playbackNotice.value = notice
  originalPlaybackConfirmed.value = false
  if (mode !== 'original') resetOriginalRecovery()
  playbackTracker.start({
    recordingId: item.id,
    codec: codecName(item.video_codec) || 'unknown',
    playbackMode: mode,
    sourceKind: metricSourceKind(item, mode),
    hevcHint: browserHevcHint.value,
  })
  videoSrc.value = src
}

function stopProgressPolling() {
  if (progressTimer !== null) window.clearInterval(progressTimer)
  progressTimer = null
}
async function refreshProxyProgress(recordingId: number) {
  if (!playerVisible.value || activeRecording.value?.id !== recordingId) return
  try {
    const response = await axios.get<PlaybackState>(`/api/recordings/${recordingId}/playback`)
    if (activeRecording.value?.id !== recordingId) return
    activeRecording.value.playback = { ...activeRecording.value.playback, ...response.data }
    proxyProgress.value = response.data.progress || null
    if (['ready', 'error', 'needed', 'direct'].includes(response.data.state)) stopProgressPolling()
  } catch {
    // Playback itself should not fail just because progress polling failed once.
  }
}
function startProgressPolling(recordingId: number) {
  stopProgressPolling()
  void refreshProxyProgress(recordingId)
  progressTimer = window.setInterval(() => void refreshProxyProgress(recordingId), 1000)
}

async function loadInitialSelection() {
  const [cameraResponse, recordingResponse] = await Promise.all([axios.get<Camera[]>('/api/cameras'), axios.get<RecentRecording[]>('/api/recordings?limit=1')])
  cameras.value = cameraResponse.data; latestRecording.value = recordingResponse.data[0] || null
  const latest = latestRecording.value
  if (latest && cameras.value.some((camera) => camera.id === latest.camera_id)) { selectedCamera.value = latest.camera_id; selectedDate.value = recordingDate(latest.started_at) || todayString() }
  else if (cameras.value.length) selectedCamera.value = cameras.value[0].id
  calendarMonth.value = selectedDate.value.slice(0, 7)
}
async function fetchDay(date: string): Promise<BrowserResult> {
  if (!selectedCamera.value) throw new Error('未选择摄像头')
  return (await axios.get<BrowserResult>('/api/recordings/browser', { params: { camera_id: selectedCamera.value, date } })).data
}
async function loadRecordings() {
  if (!selectedCamera.value || !selectedDate.value) return
  loading.value = true
  try { data.value = await fetchDay(selectedDate.value) }
  catch (error: any) { ElMessage.error(error?.response?.data?.detail || error?.message || '录像加载失败') }
  finally { loading.value = false }
}
async function loadCalendar() {
  if (!selectedCamera.value || !calendarMonth.value) return
  calendarLoading.value = true
  try { calendarData.value = (await axios.get<CalendarResult>('/api/recordings/calendar', { params: { camera_id: selectedCamera.value, month: calendarMonth.value } })).data }
  catch (error: any) { ElMessage.error(error?.response?.data?.detail || '录像日历加载失败') }
  finally { calendarLoading.value = false }
}
async function selectDay(date: string) {
  const previousMonth = calendarMonth.value; selectedDate.value = date; calendarMonth.value = date.slice(0, 7)
  if (calendarMonth.value !== previousMonth) await Promise.all([loadRecordings(), loadCalendar()]); else await loadRecordings()
}
async function handleCameraChange() { await Promise.all([loadRecordings(), loadCalendar()]) }
async function handleDateChange() { if (selectedDate.value) await selectDay(selectedDate.value) }
async function changeDay(offset: number) {
  const current = new Date(`${selectedDate.value}T12:00:00`); current.setDate(current.getDate() + offset)
  await selectDay(`${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, '0')}-${String(current.getDate()).padStart(2, '0')}`)
}
async function shiftCalendarMonth(offset: number) {
  const [year, month] = calendarMonth.value.split('-').map(Number); const target = new Date(year, month - 1 + offset, 1)
  calendarMonth.value = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}`; await loadCalendar()
}
async function selectCalendarDay(cell: CalendarCell) { if (cell.date) await selectDay(cell.date) }
async function jumpToLatest() {
  const response = await axios.get<RecentRecording[]>('/api/recordings?limit=1'); latestRecording.value = response.data[0] || null
  if (!latestRecording.value) return ElMessage.info('数据库里还没有录像记录')
  selectedCamera.value = latestRecording.value.camera_id; const date = recordingDate(latestRecording.value.started_at) || todayString()
  selectedDate.value = date; calendarMonth.value = date.slice(0, 7); await Promise.all([loadRecordings(), loadCalendar()])
}

async function prepareProxy(
  item: RecordingItem,
  automaticFallback = false,
  forceCompatibility = false,
  compatibilityReason = '',
  resumeAt = 0,
) {
  if (fallbackInProgress.value) return
  let resumePosition = Math.max(0, Number(resumeAt || 0))
  const duration = Number(item.duration || 0)
  if (Number.isFinite(duration) && duration > 0) resumePosition = Math.min(resumePosition, Math.max(0, duration - 0.25))
  compatibilityResumeAt.value = resumePosition
  pendingCompatibilitySeek.value = null
  fallbackInProgress.value = true; preparing.value = true; proxyError.value = ''; videoSrc.value = ''; proxyProgress.value = null; playbackTracker.reset(); recoveringOriginal.value = false; pendingOriginalSeek.value = null
  try {
    const state = (await axios.get<PlaybackState>(`/api/recordings/${item.id}/playback`)).data
    item.playback = { ...item.playback, ...state }
    if (state.state === 'ready') {
      pendingCompatibilitySeek.value = resumePosition > 0 ? resumePosition : null
      beginPlaybackSource(item, 'proxy', streamUrl(item.id, 'proxy'), compatibilityReason || '正在播放已缓存的 H.264 1080p 兼容版本')
      await nextTick(); return
    }
    if (state.state === 'direct' && !forceCompatibility) {
      resetCompatibilityResume()
      beginPlaybackSource(item, 'original', streamUrl(item.id, 'original'), '原片可直接播放，无需转码')
      await nextTick(); return
    }
    const fallbackText = automaticFallback ? '原片在当前浏览器解码失败，已自动切换 H.264 1080p 兼容流' : '正在生成 H.264 1080p 浏览器兼容流'
    const cloudText = isCloudOnly(item) ? 'FFmpeg 正直接读取 OpenList 远程流并转为 H.264 1080p 兼容流' : fallbackText
    const resumeText = resumePosition > 0 ? `；将从原片 ${formatDuration(resumePosition)} 继续` : ''
    beginPlaybackSource(item, 'proxy-live', liveProxyUrl(item.id, resumePosition), (compatibilityReason || cloudText) + resumeText)
    await nextTick(); startProgressPolling(item.id)
  } catch (error: any) { proxyError.value = error?.response?.data?.detail || error?.message || '播放准备失败'; ElMessage.error(proxyError.value) }
  finally { fallbackInProgress.value = false }
}
async function play(item: RecordingItem) {
  if (!isPlayable(item)) return ElMessage.warning('这段录像本地已清理且没有可用云端归档')
  stopProgressPolling(); proxyProgress.value = null; activeRecording.value = item; playerVisible.value = true; videoSrc.value = ''; proxyError.value = ''; playbackNotice.value = ''; fallbackInProgress.value = false; preparing.value = true; originalPlaybackConfirmed.value = false; resetOriginalRecovery(); resetCompatibilityResume(); playbackTracker.reset()

  if (!item.playback.original_available && !item.playback.remote_available) { preparing.value = false; proxyError.value = '本地原录像已清理，且没有成功归档记录'; return }

  const audioCompatible = isBrowserSafeAudio(item.audio_codec)
  if (!audioCompatible) {
    await prepareProxy(item, false, true, `原片音频 ${item.audio_codec || 'unknown'} 不属于 Web 安全编码，已切换 H.264 + AAC-LC 兼容模式`)
    return
  }
  if (isHevc(item.video_codec) && browserHevcHint.value === 'unsupported') {
    await prepareProxy(item, false, true, '当前浏览器未声明 HEVC/MP4 解码能力，直接使用 H.264 1080p 兼容模式')
    return
  }

  const cloudStream = isCloudOnly(item)
  if (isH264(item.video_codec) || isHevc(item.video_codec)) {
    const notice = isHevc(item.video_codec)
      ? (cloudStream ? '优先播放 OpenList 云端 HEVC 原片；播放中异常会先自动恢复原片，连续失败才切兼容流' : '优先播放 HEVC 原片；播放中异常会先自动恢复原片，连续失败才切兼容流')
      : (cloudStream ? 'OpenList 云端 H.264 原片直放；播放中异常会先自动恢复' : 'H.264 原片原画质直放；播放中异常会先自动恢复')
    beginPlaybackSource(item, 'original', streamUrl(item.id, 'original'), notice)
    await nextTick(); return
  }
  if (item.playback.state === 'ready' && !item.playback.direct) {
    beginPlaybackSource(item, 'proxy', streamUrl(item.id, 'proxy'), '正在播放已生成的 H.264 1080p 浏览器兼容缓存')
    await nextTick(); return
  }
  await prepareProxy(item, false, true, `视频编码 ${item.video_codec || 'unknown'} 不适合浏览器原生播放，已使用 H.264 兼容模式`)
}

async function navigateAdjacent(direction: AdjacentDirection, automatic = false): Promise<boolean> {
  if (!activeRecording.value || navigationLoading.value) return false
  const localTarget = direction === 'next' ? nextRecording.value : previousRecording.value
  if (localTarget) { await play(localTarget); return true }
  navigationLoading.value = true
  try {
    const response = await axios.get<AdjacentResult>(`/api/recordings/${activeRecording.value.id}/adjacent`, { params: { direction } })
    const target = response.data.item; if (!target) { if (!automatic) ElMessage.info(direction === 'next' ? '已经是最后一段可播放录像' : '已经是第一段可播放录像'); return false }
    const targetDate = response.data.date || recordingDate(target.started_at); let playableTarget = target
    if (targetDate && targetDate !== selectedDate.value) {
      const previousMonth = calendarMonth.value; selectedDate.value = targetDate; calendarMonth.value = targetDate.slice(0, 7); loading.value = true
      try { data.value = await fetchDay(targetDate) } finally { loading.value = false }
      if (calendarMonth.value !== previousMonth) await loadCalendar()
      playableTarget = data.value?.items.find((item) => item.id === target.id) || target; ElMessage.info(`${direction === 'next' ? '下一段' : '上一段'}已跨日到 ${targetDate}`)
    }
    await play(playableTarget); return true
  } catch (error: any) { ElMessage.error(error?.response?.data?.detail || error?.message || '相邻录像定位失败'); return false }
  finally { navigationLoading.value = false }
}
async function playPrevious() { await navigateAdjacent('previous') }
async function playNext() { await navigateAdjacent('next') }

function currentVideo(event?: Event) {
  return (event?.currentTarget instanceof HTMLVideoElement ? event.currentTarget : null)
}
function handleLoadedMetadata(event: Event) {
  playbackTracker.markLoadedMetadata()
  const video = currentVideo(event)
  if (!video) return
  let pending: number | null = null
  if (playbackMode.value === 'original') pending = pendingOriginalSeek.value
  else if (playbackMode.value === 'proxy') pending = pendingCompatibilitySeek.value
  if (pending === null) return
  let target = Math.max(0, pending)
  if (Number.isFinite(video.duration) && video.duration > 0) target = Math.min(target, Math.max(0, video.duration - 0.25))
  if (playbackMode.value === 'original') pendingOriginalSeek.value = null
  else pendingCompatibilitySeek.value = null
  try { video.currentTime = target } catch { /* Browser may defer seeking until loadeddata. */ }
}
function handleLoadedData(event: Event) { playbackTracker.markLoadedData(); void event }
function handleVideoCanPlay(event: Event) {
  playbackTracker.markCanPlay(currentVideo(event))
  preparing.value = false
  if (recoveringOriginal.value) playbackNotice.value = `原片已重新连接，正在从 ${formatDuration(originalRecoveryPoint.value)} 继续播放`
  else if (playbackMode.value === 'original' && isHevc(activeRecording.value?.video_codec)) playbackNotice.value = '浏览器已直接解码 HEVC 原片，保持原始画质'
  else if (playbackMode.value === 'original') playbackNotice.value = '原片直放，保持原始画质'
  else if (playbackMode.value === 'proxy-live' && compatibilityResumeAt.value > 0) playbackNotice.value = `${isCloudOnly(activeRecording.value!) ? 'OpenList 原片' : '原片'}已从 ${formatDuration(compatibilityResumeAt.value)} 继续边转边播 H.264 1080p + AAC-LC；该断点流仅用于本次续播，不会保存成半截兼容缓存`
  else if (playbackMode.value === 'proxy-live') playbackNotice.value = isCloudOnly(activeRecording.value!) ? 'OpenList 原片正在实时转为 H.264 1080p + AAC-LC；完成后缓存兼容版本' : '正在边转边播 H.264 1080p + AAC-LC；完成后缓存兼容版本'
  else if (playbackMode.value === 'proxy' && compatibilityResumeAt.value > 0) playbackNotice.value = `已切换 H.264 1080p + AAC-LC 兼容缓存，并从 ${formatDuration(compatibilityResumeAt.value)} 继续播放`
  else if (playbackMode.value === 'proxy') playbackNotice.value = '正在播放已缓存的 H.264 1080p + AAC-LC 兼容版本'
}
function handleVideoPlaying(event: Event) {
  const video = currentVideo(event)
  playbackTracker.markPlaying(video)
  if (playbackMode.value === 'original') {
    originalPlaybackConfirmed.value = true
    recoveringOriginal.value = false
    if (video && Number.isFinite(video.currentTime)) lastPlaybackTime.value = video.currentTime
  }
}
function handleVideoTimeUpdate(event: Event) {
  const video = currentVideo(event)
  if (video && Number.isFinite(video.currentTime)) lastPlaybackTime.value = video.currentTime
}
async function handleVideoEnded() {
  stopProgressPolling(); proxyProgress.value = null
  if (!autoAdvance.value) { preparing.value = false; playbackNotice.value = '当前片段播放完成，自动续播已关闭'; return }
  if (!await navigateAdjacent('next', true)) { preparing.value = false; playbackNotice.value = '已播放到该摄像头最后一个可播放片段' }
}
async function restartOriginalAfterError(item: RecordingItem, video: HTMLVideoElement | null, mediaErrorCode: number) {
  let errorAt = Math.max(0, Number(video?.currentTime || 0), lastPlaybackTime.value)
  if (originalRecoveryAttempts.value > 0 && errorAt - originalRecoveryPoint.value > 10) originalRecoveryAttempts.value = 0
  const attempt = originalRecoveryAttempts.value + 1
  originalRecoveryAttempts.value = attempt
  const decodeError = mediaErrorCode === 3 || mediaErrorCode === 4
  const skipSeconds = decodeError ? (attempt === 1 ? 2 : 5) : 0
  let resumeAt = errorAt + skipSeconds
  const duration = Number(item.duration || video?.duration || 0)
  if (Number.isFinite(duration) && duration > 0) resumeAt = Math.min(resumeAt, Math.max(0, duration - 0.25))

  originalRecoveryPoint.value = resumeAt
  pendingOriginalSeek.value = resumeAt
  recoveringOriginal.value = true
  originalPlaybackConfirmed.value = false
  preparing.value = true
  proxyError.value = ''
  const reason = mediaErrorCode === 2 ? '网络读取异常' : decodeError ? '解码异常' : '媒体读取异常'
  const skipText = skipSeconds ? `，跳过疑似损坏区间 ${skipSeconds}s` : ''
  playbackNotice.value = `${reason}（${formatDuration(errorAt)}），正在第 ${attempt}/${MAX_ORIGINAL_RECOVERY_ATTEMPTS} 次恢复原片${skipText}…`
  playbackTracker.reset()
  playbackTracker.start({
    recordingId: item.id,
    codec: codecName(item.video_codec) || 'unknown',
    playbackMode: 'original',
    sourceKind: metricSourceKind(item, 'original'),
    hevcHint: browserHevcHint.value,
  })
  videoSrc.value = streamUrl(item.id, 'original')
  await nextTick()
}
async function handleVideoError(event: Event) {
  const item = activeRecording.value; if (!playerVisible.value || !item) return
  const video = currentVideo(event)
  playbackTracker.markError(video)
  const mediaErrorCode = video?.error?.code || 0
  const errorAt = Math.max(0, Number(video?.currentTime || 0), lastPlaybackTime.value)

  if (playbackMode.value === 'original' && !fallbackInProgress.value) {
    if (originalPlaybackConfirmed.value || recoveringOriginal.value || originalRecoveryAttempts.value > 0) {
      if (originalRecoveryAttempts.value > 0 && errorAt - originalRecoveryPoint.value > 10) originalRecoveryAttempts.value = 0
      if (originalRecoveryAttempts.value < MAX_ORIGINAL_RECOVERY_ATTEMPTS) {
        await restartOriginalAfterError(item, video, mediaErrorCode)
        return
      }

      if (mediaErrorCode === 3 || mediaErrorCode === 4) {
        await prepareProxy(
          item,
          true,
          true,
          `原片在 ${formatDuration(errorAt)} 附近连续出现解码异常，原片自动恢复两次仍失败；已切换 H.264 兼容流以继续播放`,
          errorAt,
        )
        return
      }

      stopProgressPolling(); preparing.value = false; recoveringOriginal.value = false
      const reason = mediaErrorCode === 2 ? '原片网络读取连续失败' : '原片媒体读取连续失败'
      playbackNotice.value = `${reason}（${formatDuration(errorAt)}）。已自动重连两次但仍未恢复，没有因网络错误启动转码；可重新点击当前片段重试。`
      return
    }

    await prepareProxy(item, true, true, mediaErrorCode === 3 || mediaErrorCode === 4 ? '原片首帧前确认解码失败，已切换 H.264 兼容模式' : '', errorAt)
    return
  }
  stopProgressPolling(); preparing.value = false
  if (!proxyError.value) proxyError.value = playbackMode.value === 'proxy-live' ? 'H.264 兼容流启动或传输失败' : playbackMode.value === 'proxy' ? 'H.264 兼容缓存加载失败' : '原始录像无法播放'
}
async function cancelProxy() {
  const item = activeRecording.value; if (!item || cancellingProxy.value) return
  cancellingProxy.value = true; videoSrc.value = ''; stopProgressPolling(); playbackTracker.reset()
  try {
    const response = await axios.post(`/api/recordings/${item.id}/playback/cancel`)
    proxyProgress.value = null; preparing.value = false; playbackMode.value = ''; playbackNotice.value = response.data.cancelled ? 'H.264 兼容转码已停止，未完成缓存已清理' : '当前没有正在运行的兼容转码'
    item.playback.state = 'needed'; item.playback.progress = null; resetCompatibilityResume()
  } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '停止转码失败') }
  finally { cancellingProxy.value = false }
}
function closePlayer() {
  const id = activeRecording.value?.id; const shouldCancel = playbackMode.value === 'proxy-live'
  videoSrc.value = ''; stopProgressPolling(); playbackTracker.reset(); proxyProgress.value = null; playbackMode.value = ''; playbackNotice.value = ''; proxyError.value = ''; preparing.value = false; navigationLoading.value = false; fallbackInProgress.value = false; originalPlaybackConfirmed.value = false; resetOriginalRecovery(); resetCompatibilityResume()
  if (id && shouldCancel) void axios.post(`/api/recordings/${id}/playback/cancel`).catch(() => undefined)
}

onMounted(async () => { browserHevcHint.value = hevcSupportHint(); try { await loadInitialSelection(); await Promise.all([loadRecordings(), loadCalendar()]) } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '初始化失败') } })
onBeforeUnmount(() => { stopProgressPolling(); playbackTracker.reset() })
</script>

<template>
  <div class="page-shell">
    <div class="page-head"><div><h2>录像浏览</h2><p>跨日连续回看 · OpenList 云端流式回放 · 浏览器兼容自动切换</p></div></div>

    <el-card shadow="never">
      <div class="filters">
        <el-select v-model="selectedCamera" placeholder="选择摄像头" filterable style="width:240px" @change="handleCameraChange"><el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" /></el-select>
        <el-button @click="changeDay(-1)">前一天</el-button><el-date-picker v-model="selectedDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" @change="handleDateChange" /><el-button @click="changeDay(1)">后一天</el-button>
        <el-button @click="jumpToLatest">最新录像</el-button><el-button type="primary" :loading="loading" @click="loadRecordings">刷新</el-button>
      </div>
      <div v-if="data" class="summary"><span>{{ data.date }}</span><span>{{ data.timezone }}</span><span>{{ data.count }} 段</span><span>{{ formatDuration(data.total_duration) }}</span><span>{{ formatSize(data.total_size) }}</span><span v-if="remoteOnlyCount" class="cloud-summary">仅云端 {{ remoteOnlyCount }} 段</span><span :class="{ alert: timelineGaps.length }">缺口 {{ timelineGaps.length }} 处 / {{ formatDuration(totalGapSeconds) }}</span></div>
    </el-card>

    <el-card shadow="never" class="section-gap" v-loading="calendarLoading">
      <template #header><div class="calendar-head"><strong>录像日历 · {{ calendarMonth }}</strong><div><el-button size="small" @click="shiftCalendarMonth(-1)">上月</el-button><el-button size="small" @click="shiftCalendarMonth(1)">下月</el-button></div></div></template>
      <div class="calendar-weekdays"><span v-for="label in ['日','一','二','三','四','五','六']" :key="label">{{ label }}</span></div>
      <div class="recording-calendar"><div v-for="cell in calendarCells" :key="cell.key"><button v-if="cell.date" class="calendar-day" :class="{ selected: cell.date === selectedDate, has: !!cell.info, cloud: (cell.info?.remote_only || 0) > 0, warn: (cell.info?.warning_count || 0) > 0 }" @click="selectCalendarDay(cell)"><span>{{ cell.day }}</span><template v-if="cell.info"><strong>{{ cell.info.count }} 段</strong><span>{{ formatCalendarDuration(cell.info.total_duration) }}</span><small v-if="cell.info.remote_only">云端 {{ cell.info.remote_only }}</small></template><span v-else>—</span></button></div></div>
    </el-card>

    <el-card shadow="never" class="section-gap" v-loading="loading">
      <template #header><strong>24 小时时间轴</strong></template>
      <div class="axis-labels"><span v-for="hour in [0,3,6,9,12,15,18,21,24]" :key="hour">{{ String(hour).padStart(2,'0') }}:00</span></div>
      <div class="timeline"><div v-for="gap in timelineGaps" :key="gap.key" class="gap-marker" :style="gap.style" :title="`录像缺口 ${gap.startLabel}~${gap.endLabel}`" /><button v-for="item in recordings" :key="item.id" class="segment" :class="{ bad: item.health_status !== 'healthy', warning: item.warning_count > 0, cloud: isCloudOnly(item), deleted: !isPlayable(item), active: item.id === activeRecording?.id }" :style="timelineStyle(item)" :disabled="!isPlayable(item)" :title="`${localClock(item.started_at)} · ${storageLabel(item)}`" @click="play(item)" /></div>
    </el-card>

    <el-card shadow="never" class="section-gap">
      <template #header><strong>录像片段</strong></template>
      <el-table :data="recordings" stripe empty-text="当前日期暂无录像" :row-class-name="recordingRowClassName">
        <el-table-column label="开始" width="110"><template #default="{ row }">{{ localClock(row.started_at) }}</template></el-table-column><el-table-column label="时长" width="105"><template #default="{ row }">{{ formatDuration(row.duration) }}</template></el-table-column><el-table-column label="大小" width="105"><template #default="{ row }">{{ formatSize(row.file_size) }}</template></el-table-column><el-table-column prop="video_codec" label="视频" width="90" />
        <el-table-column label="位置" width="120"><template #default="{ row }"><el-tag :type="isCloudOnly(row) ? 'warning' : row.playback.original_available ? 'success' : 'info'">{{ storageLabel(row) }}</el-tag></template></el-table-column><el-table-column label="健康" width="100"><template #default="{ row }"><el-tag :type="healthType(row.health_status)">{{ row.health_status }}</el-tag></template></el-table-column><el-table-column prop="upload_status" label="上传" width="105" /><el-table-column prop="filename" label="文件" min-width="220" show-overflow-tooltip />
        <el-table-column label="播放" width="120" fixed="right"><template #default="{ row }"><el-button size="small" type="primary" :disabled="!isPlayable(row)" @click="play(row)">{{ playbackButtonLabel(row) }}</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="playerVisible" width="min(1000px,92vw)" destroy-on-close title="录像回放" @closed="closePlayer">
      <div v-if="activeRecording" class="player-meta"><strong>{{ recordingDate(activeRecording.started_at) }} {{ localClock(activeRecording.started_at) }}</strong><span>{{ formatDuration(activeRecording.duration) }}</span><span>{{ activeRecording.video_codec }}</span><span v-if="activeRecording.audio_codec">{{ activeRecording.audio_codec }}</span><span>{{ activeRecording.width }}×{{ activeRecording.height }}</span><span>{{ storageLabel(activeRecording) }}</span><span v-if="activePlayablePosition">当天 {{ activePlayablePosition }}/{{ playableRecordings.length }}</span><el-tag v-if="playbackModeLabel" :type="playbackMode === 'proxy' || playbackMode === 'proxy-live' ? 'warning' : 'success'">{{ playbackModeLabel }}</el-tag></div>
      <div class="player-controls"><div><el-button :loading="navigationLoading" :disabled="preparing || !activeRecording" @click="playPrevious">上一段</el-button><el-button :loading="navigationLoading" :disabled="preparing || !activeRecording" @click="playNext">下一段</el-button></div><label class="auto-control"><span>自动续播（可跨日）</span><el-switch v-model="autoAdvance" /></label></div>
      <div v-if="playbackNotice" class="notice">{{ playbackNotice }}</div>
      <div v-if="showProxyProgress" class="proxy-progress"><div class="progress-head"><strong>H.264 兼容转码进度</strong><span>{{ proxyProgressText }}</span></div><el-progress :percentage="effectiveProgressPercent" :stroke-width="10" /><div class="progress-actions"><span>{{ effectiveProgressPercent.toFixed(1) }}%</span><el-button size="small" type="danger" plain :loading="cancellingProxy" @click="cancelProxy">停止转码</el-button></div></div>
      <div class="player-box" v-loading="preparing || navigationLoading" :element-loading-text="playerLoadingText"><video v-if="videoSrc" :src="videoSrc" controls autoplay playsinline preload="auto" @loadedmetadata="handleLoadedMetadata" @loadeddata="handleLoadedData" @canplay="handleVideoCanPlay" @playing="handleVideoPlaying" @timeupdate="handleVideoTimeUpdate" @ended="handleVideoEnded" @error="handleVideoError" /><el-empty v-else-if="!preparing && proxyError" :description="proxyError" /><div v-else-if="preparing || navigationLoading" class="prepare-note">正在准备播放源…</div></div>
    </el-dialog>
  </div>
</template>

<style scoped>
:global(body){margin:0;background:#f5f7fa;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.page-shell{max-width:1500px;margin:0 auto;padding:24px}.page-head,.calendar-head,.player-controls,.progress-head,.progress-actions{display:flex;justify-content:space-between;align-items:center;gap:12px}.page-head{margin-bottom:18px}.page-head h2{margin:0 0 6px}.page-head p{margin:0;color:#909399}.filters,.summary,.player-meta{display:flex;flex-wrap:wrap;align-items:center;gap:12px}.summary{margin-top:14px;color:#606266;font-size:14px}.cloud-summary{color:#7c3aed;font-weight:600}.alert{color:#e6a23c;font-weight:600}.section-gap{margin-top:16px}.calendar-weekdays,.recording-calendar{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:7px}.calendar-weekdays{text-align:center;color:#909399;font-size:12px;margin-bottom:7px}.calendar-day{width:100%;min-height:76px;padding:7px;border:1px solid #ebeef5;border-radius:7px;background:#fafafa;display:flex;flex-direction:column;align-items:flex-start;gap:3px;cursor:pointer;color:#606266}.calendar-day.has{background:#f0f9eb;border-color:#b3e19d}.calendar-day.cloud{box-shadow:inset 0 -3px 0 #7c3aed}.calendar-day.warn{border-color:#e6a23c}.calendar-day.selected{outline:2px solid #409eff}.axis-labels{display:flex;justify-content:space-between;color:#909399;font-size:12px;margin-bottom:8px}.timeline{height:70px;position:relative;border:1px solid #dcdfe6;border-radius:6px;background:#fafafa;overflow:hidden}.segment{position:absolute;top:14px;height:42px;border:0;border-radius:4px;background:#67c23a;cursor:pointer;min-width:3px;z-index:2}.segment.warning{background:#e6a23c}.segment.bad{background:#f56c6c}.segment.cloud{background:#7c3aed}.segment.deleted{background:#c0c4cc}.segment.active{box-shadow:0 0 0 3px #409eff;transform:translateY(-2px)}.gap-marker{position:absolute;top:0;bottom:0;min-width:2px;background:repeating-linear-gradient(135deg,rgba(230,162,60,.35) 0,rgba(230,162,60,.35) 5px,rgba(230,162,60,.08) 5px,rgba(230,162,60,.08) 10px);z-index:1}:deep(.el-table .playing-row>td.el-table__cell){background:#ecf5ff!important}.player-meta{margin-bottom:10px;color:#606266}.player-controls{margin:8px 0 12px}.auto-control{display:flex;align-items:center;gap:8px;color:#606266;font-size:13px}.notice{padding:9px 12px;margin-bottom:10px;border-radius:6px;background:#f4f4f5;color:#606266;font-size:13px}.proxy-progress{padding:12px;margin-bottom:12px;border:1px solid #f3d19e;background:#fdf6ec;border-radius:7px}.progress-head{margin-bottom:8px;font-size:13px;color:#606266}.progress-actions{margin-top:8px;font-size:12px;color:#909399}.player-box{min-height:360px;background:#111;display:flex;align-items:center;justify-content:center;border-radius:6px;overflow:hidden}.player-box video{width:100%;max-height:70vh;background:#000}.prepare-note{color:#dcdfe6;padding:30px}@media(max-width:720px){.page-shell{padding:14px}.calendar-weekdays,.recording-calendar{gap:3px}.calendar-day{min-height:64px;padding:4px}.player-controls{align-items:flex-start;flex-direction:column}}
</style>
