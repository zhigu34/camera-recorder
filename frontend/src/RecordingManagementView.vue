<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Cloudy, Delete, Refresh, Search, VideoPlay, WarningFilled } from '@element-plus/icons-vue'
import { useCameraStore } from './stores/cameras'
import {
  PlaybackAttemptTracker,
  hevcSupportHint,
  isBrowserSafeAudio,
} from './utils/playbackCompatibility'

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
  timestamp_warning_count?: number
  network_warning_count?: number
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
interface CalendarResult { camera_id: number; month: string; timezone: string; days: CalendarDay[] }
interface CalendarCell { key: string; date?: string; day?: number; info?: CalendarDay }
interface TimelineGap {
  key: string
  durationSeconds: number
  startLabel: string
  endLabel: string
  style: Record<string, string>
}
interface AdjacentResult { direction: 'previous' | 'next'; date?: string | null; item?: RecordingItem | null }
interface RecordingDeleteResult {
  requested: number
  deleted_local: number
  archived_remote_only: number
  removed_records: number
  skipped_uploading: number[]
  already_remote_only: number[]
  not_found: number[]
  failed: Array<{ id: number; error: string }>
}

type PlaybackMode = '' | 'original' | 'proxy' | 'proxy-live'
type ActivePlaybackMode = Exclude<PlaybackMode, ''>
type AdjacentDirection = 'previous' | 'next'

const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const { cameras } = storeToRefs(cameraStore)
const playbackTracker = new PlaybackAttemptTracker()

const selectedCamera = ref<number | null>(null)
const selectedDate = ref(todayString())
const calendarMonth = ref(todayString().slice(0, 7))
const latestRecording = ref<RecentRecording | null>(null)
const browserData = ref<BrowserResult | null>(null)
const calendarData = ref<CalendarResult | null>(null)
const loading = ref(false)
const calendarLoading = ref(false)
const searchText = ref('')
const storageFilter = ref('')
const healthFilter = ref('')
const uploadFilter = ref('')
const selectedRows = ref<RecordingItem[]>([])
const deleting = ref(false)

const activeRecording = ref<RecordingItem | null>(null)
const videoSrc = ref('')
const preparing = ref(false)
const playbackMode = ref<PlaybackMode>('')
const playbackNotice = ref('')
const proxyError = ref('')
const proxyProgress = ref<ProxyProgress | null>(null)
const fallbackInProgress = ref(false)
const cancellingProxy = ref(false)
const navigationLoading = ref(false)
const autoAdvance = ref(true)
const browserHevcHint = ref(hevcSupportHint())
let progressTimer: number | null = null

const recordings = computed(() => browserData.value?.items || [])
const filteredRecordings = computed(() => {
  const needle = searchText.value.trim().toLowerCase()
  return recordings.value.filter((item) => {
    if (needle && ![item.filename, String(item.id), item.video_codec || '', item.audio_codec || ''].join(' ').toLowerCase().includes(needle)) return false
    if (storageFilter.value === 'local' && !item.playback?.original_available) return false
    if (storageFilter.value === 'cloud' && !isCloudOnly(item)) return false
    if (healthFilter.value === 'healthy' && (item.health_status !== 'healthy' || item.warning_count > 0)) return false
    if (healthFilter.value === 'abnormal' && item.health_status === 'healthy' && item.warning_count === 0) return false
    if (uploadFilter.value && item.upload_status !== uploadFilter.value) return false
    return true
  })
})
const playableRecordings = computed(() => recordings.value.filter(isPlayable))
const remoteOnlyCount = computed(() => recordings.value.filter(isCloudOnly).length)
const abnormalCount = computed(() => recordings.value.filter((item) => item.health_status !== 'healthy' || item.warning_count > 0).length)
const activeIndex = computed(() => recordings.value.findIndex((item) => item.id === activeRecording.value?.id))
const previousRecording = computed(() => findLocalAdjacent(-1))
const nextRecording = computed(() => findLocalAdjacent(1))
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
  while (cells.length % 7 !== 0) cells.push({ key: `tail-${cells.length}` })
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
      const left = gapStart / 86400 * 100
      const width = Math.max(.15, gapDuration / 86400 * 100)
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
const totalGapSeconds = computed(() => timelineGaps.value.reduce((sum, item) => sum + item.durationSeconds, 0))
const activePosition = computed(() => {
  if (!activeRecording.value) return 0
  const index = playableRecordings.value.findIndex((item) => item.id === activeRecording.value?.id)
  return index >= 0 ? index + 1 : 0
})
const playbackModeLabel = computed(() => {
  if (playbackMode.value === 'proxy-live') return 'H.264 兼容流'
  if (playbackMode.value === 'proxy') return 'H.264 兼容缓存'
  if (playbackMode.value === 'original') return '原片直放'
  return ''
})
const effectiveProgressPercent = computed(() => {
  const progress = proxyProgress.value
  if (!progress) return 0
  if (typeof progress.percent === 'number') return Math.max(0, Math.min(100, progress.percent))
  const duration = Number(activeRecording.value?.duration || progress.duration_seconds || 0)
  const elapsed = Number(progress.elapsed_seconds || 0)
  return duration ? Math.max(0, Math.min(100, elapsed / duration * 100)) : 0
})

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
function recordingDate(value?: string | null) { return value && value.length >= 10 ? value.slice(0, 10) : null }
function queryValue(value: unknown) { return Array.isArray(value) ? value[0] : value }
function positiveQueryInt(value: unknown) {
  const parsed = Number(queryValue(value) || 0)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}
function routeSelection() {
  const rawDate = queryValue(route.query.date)
  return {
    cameraId: positiveQueryInt(route.query.camera_id),
    recordingId: positiveQueryInt(route.query.recording_id),
    date: typeof rawDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(rawDate) ? rawDate : null,
  }
}
function syncRoute(item: RecordingItem | null = null) {
  const query: Record<string, string> = {}
  if (selectedCamera.value) query.camera_id = String(selectedCamera.value)
  if (selectedDate.value) query.date = selectedDate.value
  if (item) query.recording_id = String(item.id)
  void router.replace({ path: '/recordings/manage', query, hash: route.hash })
}
function formatDuration(seconds?: number | null) {
  const value = Math.max(0, Math.round(Number(seconds || 0)))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  if (hours) return `${hours}h ${minutes}m`
  if (minutes) return `${minutes}m ${secs}s`
  return `${secs}s`
}
function formatCalendarDuration(seconds?: number | null) {
  const value = Math.max(0, Number(seconds || 0))
  return value >= 3600 ? `${(value / 3600).toFixed(value >= 36000 ? 0 : 1)}h` : `${Math.round(value / 60)}m`
}
function formatSize(bytes?: number | null) {
  const value = Number(bytes || 0)
  if (!value) return '-'
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
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
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
function storageLabel(item: RecordingItem) {
  if (item.playback?.source_kind === 'openlist_stream') return 'OpenList直连'
  if (item.playback?.source_kind === 'cloud_cache') return '云端缓存'
  if (item.playback?.original_available && item.upload_status === 'success') return '本地 + 云端'
  if (item.playback?.original_available) return '本地'
  if (item.playback?.remote_available) return '仅云端'
  return '已清理'
}
function storageType(item: RecordingItem) {
  if (isCloudOnly(item)) return 'warning'
  if (item.playback?.original_available && item.upload_status === 'success') return 'success'
  return item.playback?.original_available ? 'info' : 'danger'
}
function healthType(item: RecordingItem) {
  if (item.health_status === 'healthy' && !item.warning_count) return 'success'
  return item.health_status === 'failed' ? 'danger' : 'warning'
}
function healthLabel(item: RecordingItem) {
  if (item.health_status === 'healthy' && !item.warning_count) return '健康'
  return item.health_status === 'failed' ? '失败' : `异常 ${item.warning_count || ''}`.trim()
}
function uploadLabel(value: string) {
  if (value === 'success') return '已归档'
  if (value === 'uploading') return '上传中'
  if (value === 'retry_wait') return '等待重试'
  if (value === 'failed') return '失败'
  if (value === 'pending') return '待归档'
  return value || '-'
}
function isPlayable(item: RecordingItem) {
  return Boolean(item.playback?.original_available || item.playback?.remote_available || item.playback?.state === 'ready' || item.playback?.cloud_state === 'ready')
}
function isCloudOnly(item: RecordingItem) { return !item.playback?.original_available && Boolean(item.playback?.remote_available) }
function canDelete(item: RecordingItem) { return item.status !== 'deleted' && item.upload_status !== 'uploading' }
function timelineStyle(item: RecordingItem) {
  const start = localSeconds(item.started_at)
  if (start === null) return { display: 'none' }
  const duration = Math.max(60, Number(item.duration || 0))
  const left = start / 86400 * 100
  const width = Math.max(.28, duration / 86400 * 100)
  return { left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }
}
function recordingRowClassName({ row }: { row: RecordingItem }) { return row.id === activeRecording.value?.id ? 'active-recording-row' : '' }

async function loadInitialSelection() {
  const [, recentResponse] = await Promise.all([
    cameraStore.load(),
    axios.get<RecentRecording[]>('/api/recordings?limit=1'),
  ])
  latestRecording.value = recentResponse.data[0] || null
  const deepLink = routeSelection()
  const linkedCamera = deepLink.cameraId && cameras.value.some((item) => item.id === deepLink.cameraId) ? deepLink.cameraId : null
  const latest = latestRecording.value
  if (linkedCamera) {
    selectedCamera.value = linkedCamera
    selectedDate.value = deepLink.date || todayString()
  } else if (latest && cameras.value.some((item) => item.id === latest.camera_id)) {
    selectedCamera.value = latest.camera_id
    selectedDate.value = recordingDate(latest.started_at) || todayString()
  } else if (cameras.value.length) {
    selectedCamera.value = cameras.value[0].id
  }
  calendarMonth.value = selectedDate.value.slice(0, 7)
}
async function fetchDay(date: string) {
  if (!selectedCamera.value) throw new Error('未选择摄像头')
  return (await axios.get<BrowserResult>('/api/recordings/browser', { params: { camera_id: selectedCamera.value, date } })).data
}
async function loadRecordings() {
  if (!selectedCamera.value || !selectedDate.value) return
  loading.value = true
  try {
    browserData.value = await fetchDay(selectedDate.value)
    const currentId = activeRecording.value?.id
    if (currentId) activeRecording.value = recordings.value.find((item) => item.id === currentId) || null
    if (!activeRecording.value && recordings.value.length) activeRecording.value = recordings.value[recordings.value.length - 1]
    selectedRows.value = []
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '录像加载失败')
  } finally { loading.value = false }
}
async function loadCalendar() {
  if (!selectedCamera.value || !calendarMonth.value) return
  calendarLoading.value = true
  try {
    calendarData.value = (await axios.get<CalendarResult>('/api/recordings/calendar', { params: { camera_id: selectedCamera.value, month: calendarMonth.value } })).data
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '录像日历加载失败')
  } finally { calendarLoading.value = false }
}
async function reloadAll() { await Promise.all([loadRecordings(), loadCalendar()]) }
function stopPlayback(clearSelection = false) {
  videoSrc.value = ''
  preparing.value = false
  playbackMode.value = ''
  playbackNotice.value = ''
  proxyError.value = ''
  proxyProgress.value = null
  fallbackInProgress.value = false
  stopProgressPolling()
  playbackTracker.reset()
  if (clearSelection) activeRecording.value = null
}
async function handleCameraChange() {
  stopPlayback(true)
  await reloadAll()
  syncRoute(null)
}
async function handleDateChange() {
  if (!selectedDate.value) return
  stopPlayback(true)
  calendarMonth.value = selectedDate.value.slice(0, 7)
  await reloadAll()
  syncRoute(null)
}
async function selectCalendarDay(cell: CalendarCell) {
  if (!cell.date) return
  selectedDate.value = cell.date
  await handleDateChange()
}
async function changeDay(offset: number) {
  const current = new Date(`${selectedDate.value}T12:00:00`)
  current.setDate(current.getDate() + offset)
  selectedDate.value = `${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, '0')}-${String(current.getDate()).padStart(2, '0')}`
  await handleDateChange()
}
async function shiftCalendarMonth(offset: number) {
  const [year, month] = calendarMonth.value.split('-').map(Number)
  const target = new Date(year, month - 1 + offset, 1)
  calendarMonth.value = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}`
  await loadCalendar()
}
async function jumpToLatest() {
  const response = await axios.get<RecentRecording[]>('/api/recordings?limit=1')
  latestRecording.value = response.data[0] || null
  if (!latestRecording.value) return ElMessage.info('数据库里还没有录像记录')
  selectedCamera.value = latestRecording.value.camera_id
  selectedDate.value = recordingDate(latestRecording.value.started_at) || todayString()
  calendarMonth.value = selectedDate.value.slice(0, 7)
  stopPlayback(true)
  await reloadAll()
  syncRoute(null)
}

function codecName(value?: string | null) { return (value || '').toLowerCase() }
function isH264(value?: string | null) { return ['h264', 'avc', 'avc1'].includes(codecName(value)) }
function isHevc(value?: string | null) { return ['hevc', 'h265', 'hvc1', 'hev1'].includes(codecName(value)) }
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
function beginPlaybackSource(item: RecordingItem, mode: ActivePlaybackMode, src: string, notice: string) {
  playbackMode.value = mode
  playbackNotice.value = notice
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
  if (activeRecording.value?.id !== recordingId || playbackMode.value !== 'proxy-live') return
  try {
    const response = await axios.get<PlaybackState>(`/api/recordings/${recordingId}/playback`)
    if (activeRecording.value?.id !== recordingId) return
    activeRecording.value.playback = { ...activeRecording.value.playback, ...response.data }
    proxyProgress.value = response.data.progress || null
    if (['ready', 'error', 'needed', 'direct'].includes(response.data.state)) stopProgressPolling()
  } catch { /* keep playback running */ }
}
function startProgressPolling(recordingId: number) {
  stopProgressPolling()
  void refreshProxyProgress(recordingId)
  progressTimer = window.setInterval(() => void refreshProxyProgress(recordingId), 1000)
}
async function prepareProxy(item: RecordingItem, resumeAt = 0, reason = '') {
  if (fallbackInProgress.value) return
  fallbackInProgress.value = true
  preparing.value = true
  proxyError.value = ''
  videoSrc.value = ''
  proxyProgress.value = null
  playbackTracker.reset()
  try {
    const state = (await axios.get<PlaybackState>(`/api/recordings/${item.id}/playback`)).data
    item.playback = { ...item.playback, ...state }
    if (state.state === 'ready') {
      beginPlaybackSource(item, 'proxy', streamUrl(item.id, 'proxy'), reason || '正在播放 H.264 兼容缓存')
      await nextTick()
      return
    }
    beginPlaybackSource(item, 'proxy-live', liveProxyUrl(item.id, resumeAt), reason || '正在边转边播 H.264 1080p + AAC-LC 兼容流')
    await nextTick()
    startProgressPolling(item.id)
  } catch (error) {
    proxyError.value = axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '兼容播放准备失败'
    ElMessage.error(proxyError.value)
  } finally { fallbackInProgress.value = false }
}
async function play(item: RecordingItem, forceCompatibility = false) {
  if (!isPlayable(item)) return ElMessage.warning('这段录像本地已清理且没有可用云端归档')
  stopProgressPolling()
  activeRecording.value = item
  preparing.value = true
  proxyError.value = ''
  playbackNotice.value = ''
  proxyProgress.value = null
  playbackTracker.reset()
  syncRoute(item)

  const audioCompatible = isBrowserSafeAudio(item.audio_codec)
  const directVideo = isH264(item.video_codec) || isHevc(item.video_codec)
  const hevcBlocked = isHevc(item.video_codec) && browserHevcHint.value === 'unsupported'
  if (!forceCompatibility && audioCompatible && directVideo && !hevcBlocked) {
    beginPlaybackSource(item, 'original', streamUrl(item.id, 'original'), isCloudOnly(item) ? '优先播放 OpenList 云端原片' : '原片直放，保持原始画质')
    await nextTick()
    return
  }
  const reason = forceCompatibility
    ? '已手动切换 H.264 1080p 兼容流'
    : hevcBlocked
      ? '当前浏览器未声明 HEVC 解码能力，已切换兼容流'
      : !audioCompatible
        ? `原片音频 ${item.audio_codec || 'unknown'} 不适合 Web 直放，已切换兼容流`
        : '原片编码不适合浏览器直放，已切换兼容流'
  await prepareProxy(item, 0, reason)
}
function currentVideo(event?: Event) { return event?.currentTarget instanceof HTMLVideoElement ? event.currentTarget : null }
function handleLoadedMetadata(event: Event) { playbackTracker.markLoadedMetadata(); void event }
function handleLoadedData(event: Event) { playbackTracker.markLoadedData(); void event }
function handleVideoCanPlay(event: Event) { playbackTracker.markCanPlay(currentVideo(event)); preparing.value = false }
function handleVideoPlaying(event: Event) { playbackTracker.markPlaying(currentVideo(event)); preparing.value = false }
async function handleVideoError(event: Event) {
  const item = activeRecording.value
  if (!item) return
  const video = currentVideo(event)
  playbackTracker.markError(video)
  if (playbackMode.value === 'original' && !fallbackInProgress.value) {
    const resumeAt = Math.max(0, Number(video?.currentTime || 0))
    await prepareProxy(item, resumeAt, `原片播放异常，已从 ${formatDuration(resumeAt)} 切换 H.264 兼容流`)
    return
  }
  preparing.value = false
  proxyError.value = playbackMode.value === 'proxy-live' ? 'H.264 兼容流启动或传输失败' : '录像无法播放'
}
async function cancelProxy() {
  const item = activeRecording.value
  if (!item || cancellingProxy.value) return
  cancellingProxy.value = true
  videoSrc.value = ''
  stopProgressPolling()
  try {
    await axios.post(`/api/recordings/${item.id}/playback/cancel`)
    proxyProgress.value = null
    playbackMode.value = ''
    preparing.value = false
    playbackNotice.value = '兼容转码已停止'
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '停止转码失败')
  } finally { cancellingProxy.value = false }
}
function findLocalAdjacent(step: -1 | 1) {
  for (let index = activeIndex.value + step; index >= 0 && index < recordings.value.length; index += step) {
    if (isPlayable(recordings.value[index])) return recordings.value[index]
  }
  return null
}
async function navigateAdjacent(direction: AdjacentDirection, automatic = false) {
  if (!activeRecording.value || navigationLoading.value) return false
  const local = direction === 'next' ? nextRecording.value : previousRecording.value
  if (local) { await play(local); return true }
  navigationLoading.value = true
  try {
    const response = await axios.get<AdjacentResult>(`/api/recordings/${activeRecording.value.id}/adjacent`, { params: { direction } })
    const target = response.data.item
    if (!target) {
      if (!automatic) ElMessage.info(direction === 'next' ? '已经是最后一段可播放录像' : '已经是第一段可播放录像')
      return false
    }
    const targetDate = response.data.date || recordingDate(target.started_at)
    if (targetDate && targetDate !== selectedDate.value) {
      selectedDate.value = targetDate
      calendarMonth.value = targetDate.slice(0, 7)
      await reloadAll()
    }
    const resolved = recordings.value.find((item) => item.id === target.id) || target
    await play(resolved)
    return true
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '相邻录像定位失败')
    return false
  } finally { navigationLoading.value = false }
}
async function playPrevious() { await navigateAdjacent('previous') }
async function playNext() { await navigateAdjacent('next') }
async function handleVideoEnded() {
  if (!autoAdvance.value) return
  await navigateAdjacent('next', true)
}
function selectRecording(item: RecordingItem) {
  stopPlayback(false)
  activeRecording.value = item
  syncRoute(item)
}

function deleteResultMessage(result: RecordingDeleteResult) {
  const parts: string[] = []
  if (result.archived_remote_only) parts.push(`${result.archived_remote_only} 条保留云端归档`)
  if (result.removed_records) parts.push(`${result.removed_records} 条录像已移除`)
  if (result.skipped_uploading.length) parts.push(`${result.skipped_uploading.length} 条上传中已跳过`)
  if (result.failed.length) parts.push(`${result.failed.length} 条删除失败`)
  return parts.length ? parts.join('，') : '删除完成'
}
async function deleteOne(item: RecordingItem) {
  try {
    await ElMessageBox.confirm(
      item.upload_status === 'success'
        ? `确认删除“${item.filename}”的本地文件？云端归档会保留。`
        : `确认删除“${item.filename}”？该录像尚未成功归档，删除后无法恢复。`,
      '删除录像',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
    )
  } catch { return }
  deleting.value = true
  try {
    const { data } = await axios.delete<RecordingDeleteResult>(`/api/recording-management/${item.id}`)
    if (activeRecording.value?.id === item.id) stopPlayback(true)
    ElMessage.success(deleteResultMessage(data))
    await reloadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '删除录像失败')
  } finally { deleting.value = false }
}
async function batchDelete() {
  const rows = selectedRows.value.filter(canDelete)
  if (!rows.length) return
  try {
    await ElMessageBox.confirm(`确认删除已选择的 ${rows.length} 条录像？已归档录像只删除本地文件并保留云端。`, '批量删除录像', {
      type: 'warning', confirmButtonText: `删除 ${rows.length} 条`, cancelButtonText: '取消', confirmButtonClass: 'el-button--danger',
    })
  } catch { return }
  deleting.value = true
  try {
    const { data } = await axios.post<RecordingDeleteResult>('/api/recording-management/batch-delete', { ids: rows.map((item) => item.id) })
    if (activeRecording.value && rows.some((item) => item.id === activeRecording.value?.id)) stopPlayback(true)
    ElMessage.success(deleteResultMessage(data))
    await reloadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '批量删除失败')
  } finally { deleting.value = false }
}
function handleSelectionChange(rows: RecordingItem[]) { selectedRows.value = rows }
function clearFilters() { searchText.value = ''; storageFilter.value = ''; healthFilter.value = ''; uploadFilter.value = '' }

onMounted(async () => {
  browserHevcHint.value = hevcSupportHint()
  try {
    const targetRecordingId = routeSelection().recordingId
    await loadInitialSelection()
    await reloadAll()
    if (targetRecordingId) {
      const target = recordings.value.find((item) => item.id === targetRecordingId)
      if (target) await play(target)
      else ElMessage.warning('指定录像不在当前摄像头和日期的录像列表中')
    } else if (activeRecording.value) syncRoute(activeRecording.value)
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '录像管理初始化失败')
  }
})
onBeforeUnmount(() => {
  stopProgressPolling()
  playbackTracker.reset()
  if (activeRecording.value && playbackMode.value === 'proxy-live') void axios.post(`/api/recordings/${activeRecording.value.id}/playback/cancel`).catch(() => undefined)
})
</script>

<template>
  <section class="recording-center">
    <div class="summary-grid">
      <article class="summary-card"><span class="summary-icon"><VideoPlay /></span><div><small>当日录像</small><strong>{{ browserData?.count || 0 }}</strong><em>{{ selectedDate }}</em></div></article>
      <article class="summary-card" :class="{ danger: abnormalCount > 0 }"><span class="summary-icon"><WarningFilled /></span><div><small>异常片段</small><strong>{{ abnormalCount }}</strong><em>健康检查 / 时间戳 / 网络</em></div></article>
      <article class="summary-card"><span class="summary-icon"><Cloudy /></span><div><small>仅云端</small><strong>{{ remoteOnlyCount }}</strong><em>OpenList 可回放</em></div></article>
      <article class="summary-card"><span class="summary-icon duration-icon">24</span><div><small>当日总时长</small><strong>{{ formatDuration(browserData?.total_duration) }}</strong><em>{{ formatSize(browserData?.total_size) }}</em></div></article>
    </div>

    <section class="filter-panel">
      <div class="filter-main">
        <el-select v-model="selectedCamera" filterable placeholder="选择摄像头" class="camera-select" @change="handleCameraChange">
          <el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" />
        </el-select>
        <el-date-picker v-model="selectedDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" class="date-picker" @change="handleDateChange" />
        <el-select v-model="storageFilter" clearable placeholder="存储位置" class="compact-select"><el-option label="本地" value="local" /><el-option label="仅云端" value="cloud" /></el-select>
        <el-select v-model="healthFilter" clearable placeholder="健康状态" class="compact-select"><el-option label="健康" value="healthy" /><el-option label="异常" value="abnormal" /></el-select>
        <el-select v-model="uploadFilter" clearable placeholder="归档状态" class="compact-select"><el-option label="待归档" value="pending" /><el-option label="上传中" value="uploading" /><el-option label="等待重试" value="retry_wait" /><el-option label="已归档" value="success" /><el-option label="失败" value="failed" /></el-select>
        <el-input v-model="searchText" clearable :prefix-icon="Search" placeholder="搜索文件名或录像 ID" class="search-box" />
      </div>
      <div class="filter-actions">
        <span>显示 {{ filteredRecordings.length }} / {{ recordings.length }} 段</span>
        <el-button link @click="clearFilters">清除筛选</el-button>
        <el-button :icon="Refresh" :loading="loading || calendarLoading" @click="reloadAll">刷新</el-button>
        <el-button @click="jumpToLatest">最新录像</el-button>
        <el-button @click="router.push('/uploads')">上传管理</el-button>
        <el-button v-if="selectedRows.length" type="danger" plain :icon="Delete" :loading="deleting" @click="batchDelete">删除 {{ selectedRows.length }} 条</el-button>
      </div>
    </section>

    <div class="workbench">
      <div class="browser-column">
        <section class="panel calendar-panel" v-loading="calendarLoading">
          <div class="panel-head">
            <div><strong>录像日历</strong><span>{{ calendarMonth }}</span></div>
            <div class="head-actions"><el-button size="small" @click="shiftCalendarMonth(-1)">上月</el-button><el-button size="small" @click="selectedDate = todayString(); handleDateChange()">今天</el-button><el-button size="small" @click="shiftCalendarMonth(1)">下月</el-button></div>
          </div>
          <div class="calendar-weekdays"><span v-for="label in ['日','一','二','三','四','五','六']" :key="label">周{{ label }}</span></div>
          <div class="recording-calendar">
            <div v-for="cell in calendarCells" :key="cell.key" class="calendar-cell">
              <button v-if="cell.date" class="calendar-day" :class="{ selected: cell.date === selectedDate, has: !!cell.info, cloud: (cell.info?.remote_only || 0) > 0, warn: (cell.info?.warning_count || 0) > 0 }" @click="selectCalendarDay(cell)">
                <span>{{ cell.day }}</span><strong v-if="cell.info">{{ cell.info.count }} 段</strong><small v-if="cell.info">{{ formatCalendarDuration(cell.info.total_duration) }}</small><i v-if="cell.info"></i>
              </button>
            </div>
          </div>
          <div class="calendar-legend"><span><i class="ok"></i>有录像</span><span><i class="warn"></i>有告警</span><span><i class="cloud"></i>含云端</span></div>
        </section>

        <section class="panel timeline-panel">
          <div class="panel-head"><div><strong>24 小时时间轴</strong><span>{{ selectedDate }} · 缺口 {{ timelineGaps.length }} 处 / {{ formatDuration(totalGapSeconds) }}</span></div><div class="head-actions"><el-button size="small" @click="changeDay(-1)">前一天</el-button><el-button size="small" @click="changeDay(1)">后一天</el-button></div></div>
          <div class="axis-labels"><span v-for="hour in [0,3,6,9,12,15,18,21,24]" :key="hour">{{ String(hour).padStart(2,'0') }}:00</span></div>
          <div class="timeline">
            <div v-for="gap in timelineGaps" :key="gap.key" class="gap-marker" :style="gap.style" :title="`录像缺口 ${gap.startLabel}~${gap.endLabel}`" />
            <button v-for="item in recordings" :key="item.id" class="segment" :class="{ bad: item.health_status !== 'healthy', warning: item.warning_count > 0, cloud: isCloudOnly(item), deleted: !isPlayable(item), active: item.id === activeRecording?.id }" :style="timelineStyle(item)" :disabled="!isPlayable(item)" :title="`${localClock(item.started_at)} · ${storageLabel(item)}`" @click="play(item)" />
          </div>
          <div class="timeline-legend"><span><i class="normal"></i>正常录像</span><span><i class="warning"></i>有告警</span><span><i class="cloud"></i>仅云端</span><span><i class="gap"></i>录像缺口</span></div>
        </section>

        <section class="panel list-panel" v-loading="loading">
          <div class="panel-head"><div><strong>录像片段列表</strong><span>共 {{ filteredRecordings.length }} 条</span></div></div>
          <el-table :data="filteredRecordings" row-key="id" max-height="420" empty-text="当前日期暂无录像" :row-class-name="recordingRowClassName" @selection-change="handleSelectionChange" @row-click="selectRecording">
            <el-table-column type="selection" width="42" :selectable="canDelete" />
            <el-table-column label="开始时间" width="102"><template #default="{ row }">{{ localClock(row.started_at) }}</template></el-table-column>
            <el-table-column label="时长" width="88"><template #default="{ row }">{{ formatDuration(row.duration) }}</template></el-table-column>
            <el-table-column label="大小" width="92"><template #default="{ row }">{{ formatSize(row.file_size) }}</template></el-table-column>
            <el-table-column label="位置" width="108"><template #default="{ row }"><el-tag :type="storageType(row)" size="small">{{ storageLabel(row) }}</el-tag></template></el-table-column>
            <el-table-column label="健康" width="90"><template #default="{ row }"><el-tag :type="healthType(row)" size="small">{{ healthLabel(row) }}</el-tag></template></el-table-column>
            <el-table-column label="归档" width="100"><template #default="{ row }">{{ uploadLabel(row.upload_status) }}</template></el-table-column>
            <el-table-column prop="filename" label="文件名" min-width="210" show-overflow-tooltip />
            <el-table-column label="操作" width="148" fixed="right"><template #default="{ row }"><el-button size="small" type="primary" plain :disabled="!isPlayable(row)" @click.stop="play(row)">播放</el-button><el-button size="small" type="danger" link :disabled="!canDelete(row)" @click.stop="deleteOne(row)">删除</el-button></template></el-table-column>
          </el-table>
        </section>
      </div>

      <aside id="playback-compatibility" class="player-column">
        <section class="panel player-panel">
          <div class="panel-head player-head"><div><strong>片段播放</strong><span>{{ activeRecording ? `${selectedDate} ${localClock(activeRecording.started_at)}` : '选择时间轴或列表中的录像片段' }}</span></div><el-tag v-if="playbackModeLabel" :type="playbackMode === 'original' ? 'success' : 'warning'" size="small">{{ playbackModeLabel }}</el-tag></div>
          <div class="player-box" v-loading="preparing || navigationLoading" :element-loading-text="playbackMode === 'proxy-live' ? '正在准备兼容流…' : '正在加载录像…'">
            <video v-if="videoSrc" :src="videoSrc" controls autoplay playsinline preload="auto" @loadedmetadata="handleLoadedMetadata" @loadeddata="handleLoadedData" @canplay="handleVideoCanPlay" @playing="handleVideoPlaying" @ended="handleVideoEnded" @error="handleVideoError" />
            <button v-else-if="activeRecording && isPlayable(activeRecording)" type="button" class="play-placeholder" @click="play(activeRecording)"><span><VideoPlay /></span><strong>播放当前片段</strong><small>{{ activeRecording.filename }}</small></button>
            <div v-else class="player-empty"><VideoPlay /><strong>{{ activeRecording ? '当前片段不可播放' : '尚未选择录像片段' }}</strong><span>从时间轴或片段列表中选择一段录像。</span></div>
          </div>
          <div class="player-nav"><el-button :disabled="!activeRecording" :loading="navigationLoading" @click="playPrevious">上一段</el-button><el-button type="primary" :disabled="!activeRecording || !isPlayable(activeRecording)" @click="activeRecording && play(activeRecording)">播放</el-button><el-button :disabled="!activeRecording" :loading="navigationLoading" @click="playNext">下一段</el-button></div>
          <label class="auto-advance"><span>自动续播（支持跨日）</span><el-switch v-model="autoAdvance" /></label>
          <div v-if="playbackNotice" class="playback-notice">{{ playbackNotice }}</div>
          <div v-if="proxyError" class="playback-error">{{ proxyError }}</div>
          <div v-if="playbackMode === 'proxy-live' && proxyProgress" class="proxy-progress"><div><strong>兼容转码</strong><span>{{ effectiveProgressPercent.toFixed(1) }}%</span></div><el-progress :percentage="effectiveProgressPercent" :stroke-width="8" /><el-button size="small" type="danger" plain :loading="cancellingProxy" @click="cancelProxy">停止转码</el-button></div>

          <template v-if="activeRecording">
            <div class="detail-title">当前片段信息</div>
            <dl class="detail-grid">
              <div><dt>开始时间</dt><dd>{{ selectedDate }} {{ localClock(activeRecording.started_at) }}</dd></div>
              <div><dt>时长</dt><dd>{{ formatDuration(activeRecording.duration) }}</dd></div>
              <div><dt>编码</dt><dd>{{ activeRecording.video_codec || '-' }} / {{ activeRecording.audio_codec || '-' }}</dd></div>
              <div><dt>分辨率</dt><dd>{{ activeRecording.width || '-' }} × {{ activeRecording.height || '-' }}</dd></div>
              <div><dt>存储位置</dt><dd>{{ storageLabel(activeRecording) }}</dd></div>
              <div><dt>归档状态</dt><dd>{{ uploadLabel(activeRecording.upload_status) }}</dd></div>
              <div class="wide"><dt>文件名</dt><dd>{{ activeRecording.filename }}</dd></div>
            </dl>
            <div class="player-actions"><el-button :disabled="!isPlayable(activeRecording)" @click="play(activeRecording, true)">兼容流</el-button><el-button type="danger" plain :icon="Delete" :disabled="!canDelete(activeRecording)" :loading="deleting" @click="deleteOne(activeRecording)">删除</el-button></div>
            <div v-if="activePosition" class="position-note">当天可播放片段 {{ activePosition }} / {{ playableRecordings.length }}</div>
          </template>
        </section>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.recording-center{max-width:1760px;margin:0 auto;padding:18px 20px 28px;color:var(--nvr-text)}
.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:10px}.summary-card{min-height:82px;display:flex;align-items:center;gap:12px;padding:13px 14px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.summary-card.danger{border-color:color-mix(in srgb,var(--nvr-red) 28%,var(--nvr-border))}.summary-icon{width:34px;height:34px;display:grid;place-items:center;flex:0 0 auto;border-radius:9px;color:var(--nvr-blue);background:color-mix(in srgb,var(--nvr-blue) 12%,transparent);font-weight:800}.summary-icon :deep(svg){width:17px}.summary-card.danger .summary-icon{color:var(--nvr-red);background:color-mix(in srgb,var(--nvr-red) 10%,transparent)}.summary-card>div{min-width:0;display:grid;grid-template-columns:auto 1fr;align-items:end;column-gap:8px;row-gap:4px}.summary-card small{grid-column:1/-1;color:var(--nvr-muted);font-size:10px}.summary-card strong{font-size:21px;line-height:1;font-weight:700}.summary-card em{overflow:hidden;color:var(--nvr-subtle);font-size:9px;font-style:normal;text-overflow:ellipsis;white-space:nowrap}
.filter-panel,.panel{border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.filter-panel{padding:10px;margin-bottom:10px}.filter-main{display:grid;grid-template-columns:180px 150px 125px 125px 125px minmax(220px,1fr);gap:7px}.camera-select,.date-picker,.compact-select,.search-box{width:100%!important}.filter-actions{display:flex;align-items:center;justify-content:flex-end;gap:7px;margin-top:8px;color:var(--nvr-muted);font-size:10px}
.workbench{display:grid;grid-template-columns:minmax(0,1fr) 390px;gap:10px;align-items:start}.browser-column{min-width:0;display:flex;flex-direction:column;gap:10px}.player-column{position:sticky;top:70px;min-width:0}.panel{overflow:hidden}.panel-head{min-height:42px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 11px;border-bottom:1px solid var(--nvr-border)}.panel-head>div:first-child{min-width:0;display:flex;align-items:baseline;gap:8px}.panel-head strong{font-size:12px}.panel-head span{color:var(--nvr-muted);font-size:9px}.head-actions{display:flex;gap:5px}
.calendar-panel{padding-bottom:9px}.calendar-weekdays,.recording-calendar{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px;padding:0 9px}.calendar-weekdays{padding-top:8px;padding-bottom:5px;color:var(--nvr-subtle);font-size:8px;text-align:center}.calendar-cell{min-width:0}.calendar-day{position:relative;width:100%;height:45px;display:grid;grid-template-columns:auto 1fr;grid-template-rows:auto auto;align-items:center;gap:1px 5px;padding:5px 7px;border:1px solid var(--nvr-border);border-radius:6px;color:var(--nvr-muted);background:var(--nvr-bg-soft);cursor:pointer;text-align:left}.calendar-day>span{font-size:10px}.calendar-day strong{justify-self:end;color:var(--nvr-text-soft);font-size:8px}.calendar-day small{grid-column:1/-1;color:var(--nvr-subtle);font-size:7px}.calendar-day i{position:absolute;right:5px;bottom:5px;width:4px;height:4px;border-radius:50%;background:var(--nvr-green)}.calendar-day.has{border-color:color-mix(in srgb,var(--nvr-green) 25%,var(--nvr-border));background:color-mix(in srgb,var(--nvr-green) 5%,var(--nvr-bg-soft))}.calendar-day.cloud i{background:#8b5cf6}.calendar-day.warn{border-color:color-mix(in srgb,var(--nvr-yellow) 42%,var(--nvr-border))}.calendar-day.selected{border-color:var(--nvr-blue);box-shadow:inset 0 0 0 1px var(--nvr-blue);background:color-mix(in srgb,var(--nvr-blue) 10%,var(--nvr-bg-soft))}.calendar-legend,.timeline-legend{display:flex;align-items:center;justify-content:flex-end;gap:13px;padding:7px 11px 0;color:var(--nvr-subtle);font-size:8px}.calendar-legend span,.timeline-legend span{display:inline-flex;align-items:center;gap:4px}.calendar-legend i,.timeline-legend i{width:6px;height:6px;border-radius:50%}.calendar-legend .ok,.timeline-legend .normal{background:var(--nvr-green)}.calendar-legend .warn,.timeline-legend .warning{background:var(--nvr-yellow)}.calendar-legend .cloud,.timeline-legend .cloud{background:#8b5cf6}.timeline-legend .gap{border-radius:1px;background:repeating-linear-gradient(135deg,var(--nvr-yellow) 0 2px,transparent 2px 4px)}
.timeline-panel{padding-bottom:9px}.axis-labels{display:flex;justify-content:space-between;padding:9px 11px 5px;color:var(--nvr-subtle);font-size:8px}.timeline{position:relative;height:48px;margin:0 11px;border:1px solid var(--nvr-border);border-radius:6px;background:var(--nvr-bg-soft);overflow:hidden}.segment{position:absolute;top:9px;height:28px;min-width:3px;border:0;border-radius:3px;background:var(--nvr-green);cursor:pointer;z-index:2}.segment.warning{background:var(--nvr-yellow)}.segment.bad{background:var(--nvr-red)}.segment.cloud{background:#8b5cf6}.segment.deleted{background:var(--nvr-subtle);cursor:not-allowed}.segment.active{box-shadow:0 0 0 2px var(--nvr-blue);transform:translateY(-1px)}.gap-marker{position:absolute;top:0;bottom:0;min-width:2px;background:repeating-linear-gradient(135deg,color-mix(in srgb,var(--nvr-yellow) 40%,transparent) 0 4px,transparent 4px 8px);z-index:1}
.list-panel :deep(.el-table){--el-table-bg-color:transparent;--el-table-tr-bg-color:transparent;--el-table-header-bg-color:var(--nvr-bg-soft);--el-table-border-color:var(--nvr-border);--el-table-row-hover-bg-color:var(--nvr-control-hover)}.list-panel :deep(.active-recording-row>td.el-table__cell){background:color-mix(in srgb,var(--nvr-blue) 8%,var(--nvr-surface))!important}
.player-panel{padding-bottom:11px}.player-head{border-bottom:0}.player-box{position:relative;aspect-ratio:16/9;margin:0 10px;border:1px solid var(--nvr-border);border-radius:8px;background:#03070b;overflow:hidden}.player-box video{display:block;width:100%;height:100%;object-fit:contain;background:#000}.play-placeholder{position:absolute;inset:0;width:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;border:0;color:#d8e4ef;background:radial-gradient(circle at 50% 45%,rgba(76,141,255,.12),transparent 42%),#05090d;cursor:pointer}.play-placeholder>span{width:42px;height:42px;display:grid;place-items:center;border-radius:50%;background:var(--nvr-blue)}.play-placeholder :deep(svg){width:19px}.play-placeholder strong{font-size:12px}.play-placeholder small{max-width:82%;overflow:hidden;color:#718095;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.player-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#59687b}.player-empty :deep(svg){width:28px;margin-bottom:8px}.player-empty strong{color:#8e9cac;font-size:11px}.player-empty span{margin-top:4px;font-size:8px}.player-nav{display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:6px;padding:9px 10px 0}.player-nav :deep(.el-button){margin:0}.auto-advance{display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:7px 11px 0;color:var(--nvr-muted);font-size:9px}.playback-notice,.playback-error{margin:8px 10px 0;padding:7px 8px;border-radius:6px;font-size:8px;line-height:1.45}.playback-notice{color:var(--nvr-muted);background:var(--nvr-bg-soft)}.playback-error{color:var(--nvr-red);background:color-mix(in srgb,var(--nvr-red) 8%,transparent)}.proxy-progress{margin:8px 10px 0;padding:8px;border:1px solid color-mix(in srgb,var(--nvr-yellow) 25%,var(--nvr-border));border-radius:7px;background:color-mix(in srgb,var(--nvr-yellow) 5%,transparent)}.proxy-progress>div{display:flex;justify-content:space-between;margin-bottom:6px;color:var(--nvr-muted);font-size:8px}.proxy-progress :deep(.el-button){margin-top:7px}.detail-title{padding:11px 11px 7px;color:var(--nvr-text-soft);font-size:10px;font-weight:650}.detail-grid{display:grid;grid-template-columns:1fr 1fr;margin:0 10px;border-top:1px solid var(--nvr-border)}.detail-grid>div{min-width:0;padding:7px 8px;border-bottom:1px solid var(--nvr-border)}.detail-grid>div:nth-child(odd){border-right:1px solid var(--nvr-border)}.detail-grid .wide{grid-column:1/-1;border-right:0!important}.detail-grid dt{color:var(--nvr-subtle);font-size:7px}.detail-grid dd{margin:3px 0 0;overflow-wrap:anywhere;color:var(--nvr-text-soft);font-size:8px}.player-actions{display:flex;justify-content:flex-end;gap:6px;padding:9px 10px 0}.position-note{padding:7px 10px 0;text-align:right;color:var(--nvr-subtle);font-size:8px}
@media(max-width:1250px){.workbench{grid-template-columns:minmax(0,1fr) 340px}.filter-main{grid-template-columns:repeat(3,minmax(0,1fr))}.search-box{grid-column:span 2}.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:980px){.workbench{grid-template-columns:1fr}.player-column{position:static;order:-1}.player-panel{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,1fr);gap:0 8px}.player-head{grid-column:1/-1}.player-box{grid-row:2 / span 5}.detail-title,.detail-grid,.player-actions,.position-note{grid-column:2}.player-nav,.auto-advance,.playback-notice,.playback-error,.proxy-progress{grid-column:1}.filter-actions{justify-content:flex-start;flex-wrap:wrap}}
@media(max-width:700px){.recording-center{padding:12px}.summary-grid{grid-template-columns:1fr 1fr}.filter-main{grid-template-columns:1fr 1fr}.search-box{grid-column:1/-1}.workbench{gap:8px}.player-panel{display:block}.player-box{margin-top:0}.detail-grid{grid-template-columns:1fr}.detail-grid>div:nth-child(odd){border-right:0}.detail-grid .wide{grid-column:auto}.calendar-weekdays,.recording-calendar{gap:2px;padding-left:6px;padding-right:6px}.calendar-day{height:42px;padding:4px}.calendar-day strong{display:none}.filter-actions{font-size:8px}.timeline{margin:0 8px}}
</style>
