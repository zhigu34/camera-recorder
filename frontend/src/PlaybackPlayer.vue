<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { VideoPlay } from '@element-plus/icons-vue'

import type {
  PlaybackPlayerHandle,
  PlaybackState,
  ProxyProgress,
  RecordingItem,
} from './types/recordings'
import {
  PlaybackAttemptTracker,
  hevcSupportHint,
  type PlaybackMode as MetricPlaybackMode,
} from './utils/playbackCompatibility'
import { makePlaybackOpenRequest } from './utils/playbackOpenRequest'
import { choosePlaybackSource, type PlaybackSourceReason } from './utils/playbackSourcePolicy'

type PlaybackMode = '' | 'original' | 'proxy' | 'proxy-live'
type ActivePlaybackMode = Exclude<PlaybackMode, ''>

const emit = defineEmits<{
  timeupdate: [seconds: number]
  'recording-change': [recording: RecordingItem | null]
  ended: []
  error: [message: string]
}>()

const playbackTracker = new PlaybackAttemptTracker()
const browserHevcHint = ref(hevcSupportHint())
const activeRecording = ref<RecordingItem | null>(null)
const videoRef = ref<HTMLVideoElement | null>(null)
const backdropRef = ref<HTMLCanvasElement | null>(null)
const videoSrc = ref('')
const preparing = ref(false)
const playbackMode = ref<PlaybackMode>('')
const playbackNotice = ref('')
const proxyError = ref('')
const proxyProgress = ref<ProxyProgress | null>(null)
const fallbackInProgress = ref(false)
const cancellingProxy = ref(false)
const pendingSeekSeconds = ref<number | null>(null)
let progressTimer: number | null = null

const effectiveProgressPercent = computed(() => {
  const progress = proxyProgress.value
  if (!progress) return 0
  if (typeof progress.percent === 'number') return Math.max(0, Math.min(100, progress.percent))
  const duration = Number(activeRecording.value?.duration || progress.duration_seconds || 0)
  const elapsed = Number(progress.elapsed_seconds || 0)
  return duration ? Math.max(0, Math.min(100, elapsed / duration * 100)) : 0
})

function codecName(value?: string | null) {
  return (value || '').trim().toLowerCase()
}

function isCloudOnly(item: RecordingItem) {
  return !item.playback?.original_available && Boolean(item.playback?.remote_available)
}

function isPlayable(item: RecordingItem) {
  return Boolean(
    item.playback?.original_available
    || item.playback?.remote_available
    || item.playback?.state === 'ready'
    || item.playback?.cloud_state === 'ready',
  )
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

function streamUrl(id: number, source: 'original' | 'proxy') {
  return `/api/recordings/${id}/stream?source=${source}&v=${Date.now()}`
}

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
    playbackMode: mode as MetricPlaybackMode,
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
  } catch {
    // Keep the current playback source running when progress polling fails.
  }
}

function startProgressPolling(recordingId: number) {
  stopProgressPolling()
  void refreshProxyProgress(recordingId)
  progressTimer = window.setInterval(() => void refreshProxyProgress(recordingId), 1000)
}

function sourceReasonMessage(reason: PlaybackSourceReason, item: RecordingItem) {
  if (reason === 'forced') return '已手动切换 H.264 1080p 兼容流'
  if (reason === 'hevc-unsupported') return '当前浏览器未声明 HEVC 解码能力，已切换兼容流'
  if (reason === 'audio-incompatible') return `原片音频 ${item.audio_codec || 'unknown'} 不适合 Web 直放，已切换兼容流`
  return '原片编码不适合浏览器直放，已切换兼容流'
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
    beginPlaybackSource(
      item,
      'proxy-live',
      liveProxyUrl(item.id, resumeAt),
      reason || '正在边转边播 H.264 1080p + AAC-LC 兼容流',
    )
    await nextTick()
    startProgressPolling(item.id)
  } catch (error) {
    preparing.value = false
    proxyError.value = axios.isAxiosError(error)
      ? error.response?.data?.detail || error.message
      : '兼容播放准备失败'
    ElMessage.error(proxyError.value)
    emit('error', proxyError.value)
  } finally {
    fallbackInProgress.value = false
  }
}

async function openRecordingSource(item: RecordingItem, forceCompatibility = false) {
  const decision = choosePlaybackSource({
    videoCodec: item.video_codec,
    audioCodec: item.audio_codec,
    hevcHint: browserHevcHint.value,
    forceCompatibility,
  })

  if (decision.mode === 'original') {
    beginPlaybackSource(
      item,
      'original',
      streamUrl(item.id, 'original'),
      isCloudOnly(item) ? '优先播放 OpenList 云端原片' : '原片直放，保持原始画质',
    )
    await nextTick()
    return
  }

  await prepareProxy(item, 0, sourceReasonMessage(decision.reason, item))
}

async function open(
  recording: RecordingItem,
  options: { seekSeconds?: number; forceCompatibility?: boolean } = {},
) {
  if (!isPlayable(recording)) {
    const message = '这段录像本地已清理且没有可用云端归档'
    ElMessage.warning(message)
    emit('error', message)
    return
  }

  const request = makePlaybackOpenRequest(recording, options.seekSeconds, options.forceCompatibility)
  stopProgressPolling()
  activeRecording.value = request.recording
  preparing.value = true
  proxyError.value = ''
  playbackNotice.value = ''
  proxyProgress.value = null
  playbackTracker.reset()
  pendingSeekSeconds.value = request.seekSeconds
  emit('recording-change', request.recording)
  await openRecordingSource(request.recording, request.forceCompatibility)
}

function seek(seconds: number) {
  const video = videoRef.value
  if (!video) return
  const requested = Number.isFinite(seconds) ? Math.max(0, seconds) : 0
  const maximum = Number.isFinite(video.duration) && video.duration > 0
    ? Math.max(0, video.duration - 0.1)
    : requested
  try {
    video.currentTime = Math.min(requested, maximum)
  } catch {
    // Metadata may still be unavailable. open() keeps the pending seek for loadedmetadata.
  }
}

async function playVideo() {
  if (videoRef.value) await videoRef.value.play()
}

function pause() {
  videoRef.value?.pause()
}

function drawBackdrop() {
  const video = videoRef.value
  const canvas = backdropRef.value
  if (!video || !canvas || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return
  const width = Math.min(640, video.videoWidth)
  const height = Math.max(1, Math.round(width * video.videoHeight / video.videoWidth))
  if (canvas.width !== width) canvas.width = width
  if (canvas.height !== height) canvas.height = height
  const context = canvas.getContext('2d', { alpha: false })
  if (!context) return
  try {
    context.drawImage(video, 0, 0, width, height)
  } catch {
    // The foreground remains usable if a browser refuses a transient frame draw.
  }
}

function applyPendingSeek() {
  if (pendingSeekSeconds.value === null) return
  seek(pendingSeekSeconds.value)
  pendingSeekSeconds.value = null
}

function handleLoadedMetadata() {
  playbackTracker.markLoadedMetadata()
  applyPendingSeek()
}

function handleLoadedData() {
  playbackTracker.markLoadedData()
  drawBackdrop()
}

function handleVideoCanPlay() {
  playbackTracker.markCanPlay(videoRef.value)
  preparing.value = false
  drawBackdrop()
}

function handleVideoPlaying() {
  playbackTracker.markPlaying(videoRef.value)
  preparing.value = false
  drawBackdrop()
}

function handleTimeUpdate() {
  drawBackdrop()
  emit('timeupdate', Math.max(0, Number(videoRef.value?.currentTime || 0)))
}

async function handleVideoError() {
  const item = activeRecording.value
  if (!item) return
  const video = videoRef.value
  playbackTracker.markError(video)
  if (playbackMode.value === 'original' && !fallbackInProgress.value) {
    const resumeAt = Math.max(0, Number(video?.currentTime || 0))
    await prepareProxy(item, resumeAt, `原片播放异常，已从 ${formatDuration(resumeAt)} 切换 H.264 兼容流`)
    return
  }
  preparing.value = false
  proxyError.value = playbackMode.value === 'proxy-live'
    ? 'H.264 兼容流启动或传输失败'
    : '录像无法播放'
  emit('error', proxyError.value)
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
    const message = axios.isAxiosError(error)
      ? error.response?.data?.detail || error.message
      : '停止转码失败'
    ElMessage.error(message)
    emit('error', message)
  } finally {
    cancellingProxy.value = false
  }
}

function handleEnded() {
  emit('ended')
}

function reset() {
  stopProgressPolling()
  videoSrc.value = ''
  preparing.value = false
  playbackMode.value = ''
  playbackNotice.value = ''
  proxyError.value = ''
  proxyProgress.value = null
  fallbackInProgress.value = false
  pendingSeekSeconds.value = null
  playbackTracker.reset()
}

defineExpose<PlaybackPlayerHandle>({
  open,
  seek,
  play: playVideo,
  pause,
})

onBeforeUnmount(() => {
  stopProgressPolling()
  playbackTracker.reset()
  const item = activeRecording.value
  if (item && playbackMode.value === 'proxy-live') {
    void axios.post(`/api/recordings/${item.id}/playback/cancel`).catch(() => undefined)
  }
  reset()
})
</script>

<template>
  <div class="playback-player">
    <div
      class="player-box"
      v-loading="preparing"
      :element-loading-text="playbackMode === 'proxy-live' ? '正在准备兼容流…' : '正在加载录像…'"
    >
      <template v-if="videoSrc">
        <canvas ref="backdropRef" class="player-backdrop" aria-hidden="true" />
        <video
          ref="videoRef"
          class="player-video"
          :src="videoSrc"
          controls
          autoplay
          playsinline
          preload="auto"
          @loadedmetadata="handleLoadedMetadata"
          @loadeddata="handleLoadedData"
          @canplay="handleVideoCanPlay"
          @playing="handleVideoPlaying"
          @timeupdate="handleTimeUpdate"
          @ended="handleEnded"
          @error="handleVideoError"
        />
      </template>
      <button
        v-else-if="activeRecording && isPlayable(activeRecording)"
        type="button"
        class="play-placeholder"
        @click="open(activeRecording)"
      >
        <span><VideoPlay /></span>
        <strong>播放当前片段</strong>
        <small>{{ activeRecording.filename }}</small>
      </button>
      <div v-else class="player-empty">
        <VideoPlay />
        <strong>{{ activeRecording ? '当前片段不可播放' : '尚未选择录像' }}</strong>
        <span>选择录像或时间后开始播放。</span>
      </div>
    </div>

    <div v-if="playbackNotice" class="playback-notice">{{ playbackNotice }}</div>
    <div v-if="proxyError" class="playback-error">{{ proxyError }}</div>
    <div v-if="playbackMode === 'proxy-live' && proxyProgress" class="proxy-progress">
      <div><strong>兼容转码</strong><span>{{ effectiveProgressPercent.toFixed(1) }}%</span></div>
      <el-progress :percentage="effectiveProgressPercent" :stroke-width="8" />
      <el-button size="small" type="danger" plain :loading="cancellingProxy" @click="cancelProxy">停止转码</el-button>
    </div>
  </div>
</template>

<style scoped>
.playback-player{min-width:0}.player-box{position:relative;aspect-ratio:16/9;border:1px solid var(--nvr-border);border-radius:8px;background:#03070b;overflow:hidden}.player-backdrop{position:absolute;inset:-20px;width:calc(100% + 40px);height:calc(100% + 40px);object-fit:cover;filter:blur(20px) brightness(.48) saturate(.82);transform:scale(1.06);pointer-events:none}.player-video{position:relative;z-index:1;display:block;width:100%;height:100%;object-fit:contain;background:transparent}.play-placeholder{position:absolute;inset:0;width:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;border:0;color:#d8e4ef;background:radial-gradient(circle at 50% 45%,rgba(76,141,255,.12),transparent 42%),#05090d;cursor:pointer}.play-placeholder>span{width:42px;height:42px;display:grid;place-items:center;border-radius:50%;background:var(--nvr-blue)}.play-placeholder :deep(svg){width:19px}.play-placeholder strong{font-size:12px}.play-placeholder small{max-width:82%;overflow:hidden;color:#718095;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.player-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#59687b}.player-empty :deep(svg){width:28px;margin-bottom:8px}.player-empty strong{color:#8e9cac;font-size:11px}.player-empty span{margin-top:4px;font-size:8px}.playback-notice,.playback-error{margin-top:8px;padding:7px 8px;border-radius:6px;font-size:8px;line-height:1.45}.playback-notice{color:var(--nvr-muted);background:var(--nvr-bg-soft)}.playback-error{color:var(--nvr-red);background:color-mix(in srgb,var(--nvr-red) 8%,transparent)}.proxy-progress{margin-top:8px;padding:8px;border:1px solid color-mix(in srgb,var(--nvr-yellow) 25%,var(--nvr-border));border-radius:7px;background:color-mix(in srgb,var(--nvr-yellow) 5%,transparent)}.proxy-progress>div{display:flex;justify-content:space-between;margin-bottom:6px;color:var(--nvr-muted);font-size:8px}.proxy-progress :deep(.el-button){margin-top:7px}
</style>