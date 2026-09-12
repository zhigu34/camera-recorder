<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, Search, VideoPlay } from '@element-plus/icons-vue'
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
interface HeatBin {
  index: number
  start: number
  end: number
  level: number
  coverage: number
  items: RecordingItem[]
  warning: boolean
  cloud: boolean
  active: boolean
  title: string
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
const currentCameraName = computed(() => cameras.value.find((item) => item.id === selectedCamera.value)?.name || '未选择摄像头')
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
const heatBins = computed<HeatBin[]>(() => {
  const binSeconds = 5 * 60
  return Array.from({ length: 288 }, (_, index) => {
    const start = index * binSeconds
    const end = start + binSeconds
    const items = recordings.value.filter((item) => {
      const range = recordingRange(item)
      return range ? range.start < end && range.end > start : false
    })
    const coverage = Math.min(binSeconds, items.reduce((total, item) => {
      const range = recordingRange(item)
      if (!range) return total
      return total + Math.max(0, Math.min(end, range.end) - Math.max(start, range.start))
    }, 0))
    const ratio = coverage / binSeconds
    const level = coverage <= 0 ? 0 : ratio < .25 ? 1 : ratio < .5 ? 2 : ratio < .8 ? 3 : 4
    const warning = items.some((item) => item.health_status !== 'healthy' || item.warning_count > 0)
    const cloud = items.some(isCloudOnly)
    const active = activeRecording.value ? items.some((item) => item.id === activeRecording.value?.id) : false
    return {
      index,
      start,
      end,
      level,
      coverage,
      items,
      warning,
      cloud,
      active,
      title: `${clockFromSeconds(start)}–${clockFromSeconds(end)} · ${items.length} 段 · ${formatDuration(coverage)}`,
    }
  })
})
const heatHourLabels = Array.from({ length: 13 }, (_, index) => index * 2)
const heatMinuteLabels = Array.from({ length: 12 }, (_, index) => index * 5)
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
function recordingRange(item: RecordingItem) {
  const start = localSeconds(item.started_at)
  if (start === null) return null
  const explicitEnd = localSeconds(item.ended_at)
  const duration = Math.max(0, Number(item.duration || 0))
  const end = Math.max(start, Math.min(86400, explicitEnd ?? start + duration))
  return { start, end }
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
async function shiftCalendarMonth(offset: number) {
  const [year, month] = calendarMonth.value.split('-').map(Number)
  const target = new Date(year, month - 1 + offset, 1)
  calendarMonth.value = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}`
  await loadCalendar()
}
async function jumpToToday() {
  selectedDate.value = todayString()
  await handleDateChange()
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
  } catch { /* playback keeps running */ }
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
    preparing.value = false
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
async function playHeatBin(bin: HeatBin) {
  const target = bin.items.find(isPlayable)
  if (target) await play(target)
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
    <div class="recording-layout">
      <aside id="playback-compatibility" class="playback-column">
        <section class="panel player-panel">
          <div class="panel-head player-head">
            <div><strong>片段播放</strong><span>{{ activeRecording ? `${selectedDate} ${localClock(activeRecording.started_at)}` : '选择录像片段' }}</span></div>
            <div class="player-head-meta"><el-tag size="small" type="primary">{{ currentCameraName }}</el-tag><el-tag v-if="playbackModeLabel" :type="playbackMode === 'original' ? 'success' : 'warning'" size="small">{{ playbackModeLabel }}</el-tag></div>
          </div>

          <div class="player-box" v-loading="preparing || navigationLoading" :element-loading-text="playbackMode === 'proxy-live' ? '正在准备兼容流…' : '正在加载录像…'">
            <video v-if="videoSrc" :src="videoSrc" controls autoplay playsinline preload="auto" @loadedmetadata="handleLoadedMetadata" @loadeddata="handleLoadedData" @canplay="handleVideoCanPlay" @playing="handleVideoPlaying" @ended="handleVideoEnded" @error="handleVideoError" />
            <button v-else-if="activeRecording && isPlayable(activeRecording)" type="button" class="play-placeholder" @click="play(activeRecording)"><span><VideoPlay /></span><strong>播放当前片段</strong><small>{{ activeRecording.filename }}</small></button>
            <div v-else class="player-empty"><VideoPlay /><strong>{{ activeRecording ? '当前片段不可播放' : '尚未选择录像片段' }}</strong><span>从右侧录像列表或热力图中选择一段录像。</span></div>
          </div>

          <div class="player-nav"><el-button :disabled="!activeRecording" :loading="navigationLoading" @click="playPrevious">上一段</el-button><el-button type="primary" :disabled="!activeRecording || !isPlayable(activeRecording)" @click="activeRecording && play(activeRecording)"><VideoPlay class="button-icon" />播放</el-button><el-button :disabled="!activeRecording" :loading="navigationLoading" @click="playNext">下一段</el-button></div>
          <label class="auto-advance"><span>自动续播（支持跨日）</span><el-switch v-model="autoAdvance" /></label>
          <div v-if="playbackNotice" class="playback-notice">{{ playbackNotice }}</div>
          <div v-if="proxyError" class="playback-error">{{ proxyError }}</div>
          <div v-if="playbackMode === 'proxy-live' && proxyProgress" class="proxy-progress"><div><strong>兼容转码</strong><span>{{ effectiveProgressPercent.toFixed(1) }}%</span></div><el-progress :percentage="effectiveProgressPercent" :stroke-width="8" /><el-button size="small" type="danger" plain :loading="cancellingProxy" @click="cancelProxy">停止转码</el-button></div>

          <section class="heat-section">
            <div class="section-head"><div><strong>24 小时录像热力图</strong><span>5 分钟/格 · {{ selectedDate }}</span></div><span>{{ recordings.length }} 段 · {{ formatDuration(browserData?.total_duration) }}</span></div>
            <div class="heat-map">
              <div class="heat-grid">
                <button v-for="bin in heatBins" :key="bin.index" type="button" class="heat-cell" :class="[`level-${bin.level}`, { warning: bin.warning, cloud: bin.cloud, active: bin.active }]" :disabled="!bin.items.some(isPlayable)" :title="bin.title" @click="playHeatBin(bin)" />
              </div>
              <div class="heat-minutes" aria-hidden="true"><span v-for="minute in heatMinuteLabels" :key="minute">{{ String(minute).padStart(2, '0') }}</span></div>
            </div>
            <div class="heat-axis"><span v-for="hour in heatHourLabels" :key="hour">{{ String(hour).padStart(2, '0') }}:00</span></div>
            <div class="heat-legend"><span><i class="heat-normal"></i>录像覆盖</span><span><i class="heat-warning"></i>有告警</span><span><i class="heat-cloud"></i>含云端</span><span><i class="heat-empty"></i>无录像</span></div>
          </section>

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

      <div class="catalog-column">
        <section class="panel calendar-panel" v-loading="calendarLoading">
          <div class="panel-head calendar-head">
            <div><strong>录像日历</strong><span>{{ calendarMonth }}</span></div>
            <div class="calendar-summary"><span>当日 {{ recordings.length }} 段</span><span>{{ formatDuration(browserData?.total_duration) }}</span><span :class="{ danger: abnormalCount > 0 }">异常 {{ abnormalCount }}</span><span>仅云端 {{ remoteOnlyCount }}</span></div>
            <div class="head-actions"><el-button size="small" @click="shiftCalendarMonth(-1)">‹</el-button><el-button size="small" @click="jumpToToday">今天</el-button><el-button size="small" @click="shiftCalendarMonth(1)">›</el-button></div>
          </div>

          <div class="calendar-toolbar">
            <el-select v-model="selectedCamera" filterable placeholder="选择摄像头" class="camera-select" @change="handleCameraChange"><el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" /></el-select>
            <el-date-picker v-model="selectedDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" class="date-picker" @change="handleDateChange" />
            <el-select v-model="storageFilter" clearable placeholder="存储位置" class="compact-select"><el-option label="本地" value="local" /><el-option label="仅云端" value="cloud" /></el-select>
            <el-select v-model="healthFilter" clearable placeholder="健康状态" class="compact-select"><el-option label="健康" value="healthy" /><el-option label="异常" value="abnormal" /></el-select>
            <el-select v-model="uploadFilter" clearable placeholder="归档状态" class="compact-select"><el-option label="待归档" value="pending" /><el-option label="上传中" value="uploading" /><el-option label="等待重试" value="retry_wait" /><el-option label="已归档" value="success" /><el-option label="失败" value="failed" /></el-select>
            <el-input v-model="searchText" clearable :prefix-icon="Search" placeholder="搜索文件名或录像 ID" class="search-box" />
          </div>
          <div class="calendar-actions"><span>显示 {{ filteredRecordings.length }} / {{ recordings.length }} 段</span><el-button link @click="clearFilters">清除筛选</el-button><el-button :icon="Refresh" :loading="loading || calendarLoading" @click="reloadAll">刷新</el-button><el-button @click="jumpToLatest">最新录像</el-button><el-button @click="router.push('/uploads')">上传管理</el-button><el-button v-if="selectedRows.length" type="danger" plain :icon="Delete" :loading="deleting" @click="batchDelete">删除 {{ selectedRows.length }} 条</el-button></div>

          <div class="calendar-weekdays"><span v-for="label in ['日','一','二','三','四','五','六']" :key="label">周{{ label }}</span></div>
          <div class="recording-calendar">
            <div v-for="cell in calendarCells" :key="cell.key" class="calendar-cell">
              <button v-if="cell.date" class="calendar-day" :class="{ selected: cell.date === selectedDate, has: !!cell.info, cloud: (cell.info?.remote_only || 0) > 0, warn: (cell.info?.warning_count || 0) > 0 }" @click="selectCalendarDay(cell)"><span>{{ cell.day }}</span><strong v-if="cell.info">{{ cell.info.count }} 段</strong><i v-if="cell.info"></i></button>
            </div>
          </div>
          <div class="calendar-legend"><span><i class="ok"></i>有录像</span><span><i class="warn"></i>有告警</span><span><i class="cloud"></i>含云端</span></div>
        </section>

        <section class="panel list-panel" v-loading="loading">
          <div class="panel-head"><div><strong>录像片段列表</strong><span>共 {{ filteredRecordings.length }} 条</span></div><span class="list-hint">单击选择 · 双击播放</span></div>
          <el-table :data="filteredRecordings" row-key="id" max-height="520" empty-text="当前日期暂无录像" :row-class-name="recordingRowClassName" @selection-change="handleSelectionChange" @row-click="selectRecording" @row-dblclick="play">
            <el-table-column type="selection" width="42" :selectable="canDelete" />
            <el-table-column label="开始时间" width="96"><template #default="{ row }">{{ localClock(row.started_at) }}</template></el-table-column>
            <el-table-column label="时长" width="82"><template #default="{ row }">{{ formatDuration(row.duration) }}</template></el-table-column>
            <el-table-column label="大小" width="88"><template #default="{ row }">{{ formatSize(row.file_size) }}</template></el-table-column>
            <el-table-column label="位置" width="104"><template #default="{ row }"><el-tag :type="storageType(row)" size="small">{{ storageLabel(row) }}</el-tag></template></el-table-column>
            <el-table-column label="健康" width="84"><template #default="{ row }"><el-tag :type="healthType(row)" size="small">{{ healthLabel(row) }}</el-tag></template></el-table-column>
            <el-table-column label="归档" width="90"><template #default="{ row }">{{ uploadLabel(row.upload_status) }}</template></el-table-column>
            <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip />
            <el-table-column label="操作" width="132" fixed="right"><template #default="{ row }"><el-button size="small" type="primary" plain :disabled="!isPlayable(row)" @click.stop="play(row)">播放</el-button><el-button size="small" type="danger" link :disabled="!canDelete(row)" @click.stop="deleteOne(row)">删除</el-button></template></el-table-column>
          </el-table>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.recording-center{max-width:1840px;margin:0 auto;padding:16px 18px 26px;color:var(--nvr-text)}
.recording-layout{display:grid;grid-template-columns:minmax(430px,.9fr) minmax(650px,1.25fr);gap:12px;align-items:start}.playback-column{position:sticky;top:70px;min-width:0;align-self:start}.catalog-column{min-width:0;display:flex;flex-direction:column;gap:10px}.panel{overflow:hidden;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.panel-head{min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 11px;border-bottom:1px solid var(--nvr-border)}.panel-head>div:first-child{min-width:0;display:flex;align-items:baseline;gap:8px}.panel-head strong{font-size:12px}.panel-head span{color:var(--nvr-muted);font-size:9px}.head-actions{display:flex;gap:5px}.head-actions :deep(.el-button){margin:0}.button-icon{width:13px;margin-right:4px}
.player-panel{max-height:calc(100vh - 108px);overflow-y:auto;padding-bottom:12px;scrollbar-gutter:stable}.player-head{border-bottom:0}.player-head-meta{display:flex;align-items:center;gap:5px}.player-box{position:relative;aspect-ratio:16/9;margin:0 11px;border:1px solid var(--nvr-border);border-radius:8px;background:#03070b;overflow:hidden}.player-box video{display:block;width:100%;height:100%;object-fit:contain;background:#000}.play-placeholder{position:absolute;inset:0;width:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;border:0;color:#d8e4ef;background:radial-gradient(circle at 50% 45%,rgba(76,141,255,.12),transparent 42%),#05090d;cursor:pointer}.play-placeholder>span{width:42px;height:42px;display:grid;place-items:center;border-radius:50%;background:var(--nvr-blue)}.play-placeholder :deep(svg){width:19px}.play-placeholder strong{font-size:12px}.play-placeholder small{max-width:82%;overflow:hidden;color:#718095;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.player-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#59687b}.player-empty :deep(svg){width:28px;margin-bottom:8px}.player-empty strong{color:#8e9cac;font-size:11px}.player-empty span{margin-top:4px;font-size:8px}.player-nav{display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:6px;padding:9px 11px 0}.player-nav :deep(.el-button){min-height:34px;margin:0}.auto-advance{display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:7px 12px 0;color:var(--nvr-muted);font-size:9px}.playback-notice,.playback-error{margin:8px 11px 0;padding:7px 8px;border-radius:6px;font-size:8px;line-height:1.45}.playback-notice{color:var(--nvr-muted);background:var(--nvr-bg-soft)}.playback-error{color:var(--nvr-red);background:color-mix(in srgb,var(--nvr-red) 8%,transparent)}.proxy-progress{margin:8px 11px 0;padding:8px;border:1px solid color-mix(in srgb,var(--nvr-yellow) 25%,var(--nvr-border));border-radius:7px;background:color-mix(in srgb,var(--nvr-yellow) 5%,transparent)}.proxy-progress>div{display:flex;justify-content:space-between;margin-bottom:6px;color:var(--nvr-muted);font-size:8px}.proxy-progress :deep(.el-button){margin-top:7px}
.heat-section{margin-top:10px;padding:11px;border-top:1px solid var(--nvr-border);border-bottom:1px solid var(--nvr-border);background:color-mix(in srgb,var(--nvr-bg-soft) 55%,transparent)}.section-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.section-head>div{display:flex;align-items:baseline;gap:7px}.section-head strong{font-size:11px}.section-head span{color:var(--nvr-subtle);font-size:8px}.heat-grid{display:grid;grid-template-columns:repeat(24,minmax(0,1fr));grid-template-rows:repeat(6,8px);grid-auto-flow:column;gap:2px 3px}.heat-cell{height:auto;min-height:8px;border:1px solid color-mix(in srgb,var(--nvr-border) 80%,transparent);border-radius:2px;background:var(--nvr-bg);cursor:pointer;transition:filter .12s ease,transform .12s ease,box-shadow .12s ease}.heat-cell.level-1{background:color-mix(in srgb,var(--nvr-green) 24%,var(--nvr-bg))}.heat-cell.level-2{background:color-mix(in srgb,var(--nvr-green) 42%,var(--nvr-bg))}.heat-cell.level-3{background:color-mix(in srgb,var(--nvr-green) 66%,var(--nvr-bg))}.heat-cell.level-4{background:color-mix(in srgb,var(--nvr-green) 88%,var(--nvr-bg))}.heat-cell.warning{border-color:var(--nvr-yellow);box-shadow:inset 0 -2px 0 var(--nvr-yellow)}.heat-cell.cloud{box-shadow:inset 0 2px 0 #8b5cf6}.heat-cell.warning.cloud{box-shadow:inset 0 -2px 0 var(--nvr-yellow),inset 0 2px 0 #8b5cf6}.heat-cell.active{outline:2px solid var(--nvr-blue);outline-offset:1px;z-index:2}.heat-cell:not(:disabled):hover{filter:brightness(1.18);transform:translateY(-1px)}.heat-cell:disabled{cursor:default;opacity:.7}.heat-axis{display:flex;justify-content:space-between;margin-top:5px;color:var(--nvr-subtle);font-size:7px}.heat-legend{display:flex;justify-content:flex-end;gap:11px;margin-top:7px;color:var(--nvr-subtle);font-size:7px}.heat-legend span{display:inline-flex;align-items:center;gap:4px}.heat-legend i{width:6px;height:6px;border-radius:2px}.heat-normal{background:var(--nvr-green)}.heat-warning{background:var(--nvr-yellow)}.heat-cloud{background:#8b5cf6}.heat-empty{border:1px solid var(--nvr-border);background:var(--nvr-bg)}
.detail-title{padding:11px 11px 7px;color:var(--nvr-text-soft);font-size:10px;font-weight:650}.detail-grid{display:grid;grid-template-columns:1fr 1fr;margin:0 10px;border-top:1px solid var(--nvr-border)}.detail-grid>div{min-width:0;padding:8px;border-bottom:1px solid var(--nvr-border)}.detail-grid>div:nth-child(odd){border-right:1px solid var(--nvr-border)}.detail-grid .wide{grid-column:1/-1;border-right:0!important}.detail-grid dt{color:var(--nvr-subtle);font-size:7px}.detail-grid dd{margin:3px 0 0;overflow-wrap:anywhere;color:var(--nvr-text-soft);font-size:8px}.player-actions{display:flex;justify-content:flex-end;gap:6px;padding:9px 10px 0}.position-note{padding:7px 10px 0;text-align:right;color:var(--nvr-subtle);font-size:8px}
.calendar-head{min-height:46px}.calendar-summary{display:flex;align-items:center;gap:10px;margin-left:auto;color:var(--nvr-subtle);font-size:8px}.calendar-summary span{white-space:nowrap}.calendar-summary .danger{color:var(--nvr-red)}.calendar-toolbar{display:grid;grid-template-columns:180px 145px 110px 110px 115px minmax(180px,1fr);gap:6px;padding:9px 10px 7px;border-bottom:1px solid var(--nvr-border)}.camera-select,.date-picker,.compact-select,.search-box{width:100%!important}.calendar-actions{display:flex;align-items:center;justify-content:flex-end;gap:6px;padding:0 10px 8px;color:var(--nvr-muted);font-size:8px;border-bottom:1px solid var(--nvr-border)}.calendar-actions :deep(.el-button){margin:0}.calendar-weekdays,.recording-calendar{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:3px;padding:0 9px}.calendar-weekdays{padding-top:7px;padding-bottom:4px;color:var(--nvr-subtle);font-size:8px;text-align:center}.calendar-cell{min-width:0}.calendar-day{position:relative;width:100%;height:35px;display:grid;grid-template-columns:auto 1fr;align-items:center;gap:4px;padding:4px 6px;border:1px solid var(--nvr-border);border-radius:5px;color:var(--nvr-muted);background:var(--nvr-bg-soft);cursor:pointer;text-align:left}.calendar-day>span{font-size:9px}.calendar-day strong{justify-self:end;color:var(--nvr-text-soft);font-size:7px}.calendar-day i{position:absolute;right:4px;bottom:4px;width:4px;height:4px;border-radius:50%;background:var(--nvr-green)}.calendar-day.has{border-color:color-mix(in srgb,var(--nvr-green) 25%,var(--nvr-border));background:color-mix(in srgb,var(--nvr-green) 5%,var(--nvr-bg-soft))}.calendar-day.cloud i{background:#8b5cf6}.calendar-day.warn{border-color:color-mix(in srgb,var(--nvr-yellow) 42%,var(--nvr-border))}.calendar-day.selected{border-color:var(--nvr-blue);box-shadow:inset 0 0 0 1px var(--nvr-blue);background:color-mix(in srgb,var(--nvr-blue) 10%,var(--nvr-bg-soft))}.calendar-legend{display:flex;align-items:center;justify-content:flex-end;gap:12px;padding:6px 10px 8px;color:var(--nvr-subtle);font-size:7px}.calendar-legend span{display:inline-flex;align-items:center;gap:4px}.calendar-legend i{width:6px;height:6px;border-radius:50%}.calendar-legend .ok{background:var(--nvr-green)}.calendar-legend .warn{background:var(--nvr-yellow)}.calendar-legend .cloud{background:#8b5cf6}
.list-panel .panel-head{min-height:40px}.list-hint{margin-left:auto}.list-panel :deep(.el-table){--el-table-bg-color:transparent;--el-table-tr-bg-color:transparent;--el-table-header-bg-color:var(--nvr-bg-soft);--el-table-border-color:var(--nvr-border);--el-table-row-hover-bg-color:var(--nvr-control-hover);color:var(--nvr-text-soft);font-size:10px}.list-panel :deep(.el-table th.el-table__cell){height:34px;padding:4px 0;color:var(--nvr-subtle);font-size:8px;font-weight:650}.list-panel :deep(.el-table td.el-table__cell){padding:6px 0}.list-panel :deep(.el-table__row){cursor:pointer}.list-panel :deep(.active-recording-row>td.el-table__cell){background:color-mix(in srgb,var(--nvr-blue) 10%,var(--nvr-surface))!important}.list-panel :deep(.el-tag){min-height:20px;line-height:18px}.list-panel :deep(.el-button--small){min-height:26px;padding-left:8px;padding-right:8px}
@media(max-width:1380px){.recording-layout{grid-template-columns:minmax(400px,.82fr) minmax(580px,1.18fr)}.calendar-toolbar{grid-template-columns:repeat(3,minmax(0,1fr))}.search-box{grid-column:span 2}.calendar-summary span:nth-child(4){display:none}}
@media(max-width:1080px){.recording-layout{grid-template-columns:1fr}.playback-column{position:static}.player-panel{max-height:none}.calendar-summary{display:none}.catalog-column{order:2}.playback-column{order:1}}
@media(max-width:700px){.recording-center{padding:10px}.calendar-toolbar{grid-template-columns:1fr 1fr}.search-box{grid-column:1/-1}.calendar-actions{justify-content:flex-start;flex-wrap:wrap}.heat-grid{grid-template-rows:repeat(6,7px);gap:2px}.heat-cell{height:auto;min-height:7px}.heat-axis span:nth-child(even){display:none}.detail-grid{grid-template-columns:1fr}.detail-grid>div:nth-child(odd){border-right:0}.detail-grid .wide{grid-column:auto}.calendar-day{height:32px}.calendar-day strong{display:none}.player-head-meta .el-tag:first-child{display:none}}
</style>
