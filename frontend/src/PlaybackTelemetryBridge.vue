<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

interface PlaybackState {
  video_codec?: string | null
  source_kind?: string | null
}

interface Attempt {
  id: string
  recordingId: number
  startedAt: number
  playbackMode: string
  codec: string
  sourceKind: string
  metadataMs?: number
  loadedDataMs?: number
  canplayMs?: number
  playingMs?: number
  decodeReported: boolean
  firstFrameReported: boolean
  errorReported: boolean
  frameCallbackArmed: boolean
  enrichment?: Promise<void>
}

const attempts = new WeakMap<HTMLVideoElement, Attempt>()
const listeners: Array<[string, EventListener]> = []
const sourcePattern = /\/api\/recordings\/(\d+)\/(stream|proxy-live\.mp4)/

function nowMs() { return performance.now() }
function elapsed(attempt: Attempt) { return Math.max(0, Number((nowMs() - attempt.startedAt).toFixed(1))) }

function browserInfo() {
  const ua = navigator.userAgent
  const candidates: Array<[string, RegExp]> = [
    ['Edge', /Edg(?:A|iOS)?\/(\d+)/],
    ['Chrome', /(?:Chrome|CriOS)\/(\d+)/],
    ['Firefox', /(?:Firefox|FxiOS)\/(\d+)/],
    ['Safari', /Version\/(\d+).+Safari/],
  ]
  for (const [browser, pattern] of candidates) {
    const match = ua.match(pattern)
    if (match) return { browser, version: match[1] || 'unknown' }
  }
  return { browser: 'Other', version: 'unknown' }
}

function platformLabel() {
  const extended = navigator as Navigator & { userAgentData?: { platform?: string } }
  const raw = extended.userAgentData?.platform || navigator.platform || 'unknown'
  const ua = navigator.userAgent
  if (/iPhone|iPad|iPod/i.test(ua)) return 'iOS'
  if (/Android/i.test(ua)) return 'Android'
  if (/Mac/i.test(raw)) return 'macOS'
  if (/Win/i.test(raw)) return 'Windows'
  if (/Linux/i.test(raw)) return 'Linux'
  return raw.slice(0, 32) || 'unknown'
}

function hevcHint(video: HTMLVideoElement) {
  return video.canPlayType('video/mp4; codecs="hvc1"') || video.canPlayType('video/mp4; codecs="hev1"') || 'unsupported'
}

function playbackModeFromSource(source: string) {
  if (source.includes('/proxy-live.mp4')) return 'proxy-live'
  if (source.includes('source=proxy')) return 'proxy'
  if (source.includes('source=original')) return 'original'
  return 'unknown'
}

function recordingIdFromVideo(video: HTMLVideoElement) {
  const source = video.getAttribute('src') || ''
  const match = source.match(sourcePattern)
  return match ? { recordingId: Number(match[1]), source } : null
}

async function enrichAttempt(attempt: Attempt) {
  try {
    const response = await fetch(`/api/recordings/${attempt.recordingId}/playback`, { cache: 'no-store' })
    if (!response.ok) return
    const state = await response.json() as PlaybackState
    attempt.codec = (state.video_codec || 'unknown').toLowerCase()
    attempt.sourceKind = state.source_kind || 'unknown'
  } catch {
    // Telemetry metadata must never interfere with playback.
  }
}

function startAttempt(video: HTMLVideoElement) {
  const target = recordingIdFromVideo(video)
  if (!target) return
  const attempt: Attempt = {
    id: `${target.recordingId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    recordingId: target.recordingId,
    startedAt: nowMs(),
    playbackMode: playbackModeFromSource(target.source),
    codec: 'unknown',
    sourceKind: 'unknown',
    decodeReported: false,
    firstFrameReported: false,
    errorReported: false,
    frameCallbackArmed: false,
  }
  attempt.enrichment = enrichAttempt(attempt)
  attempts.set(video, attempt)
}

async function report(
  video: HTMLVideoElement,
  attempt: Attempt,
  event: 'decode_ready' | 'first_frame' | 'startup_error' | 'playback_error',
  durationMs: number | undefined,
  signal: string,
) {
  try {
    if (attempt.enrichment) {
      await Promise.race([
        attempt.enrichment,
        new Promise<void>((resolve) => window.setTimeout(resolve, 300)),
      ])
    }
    const browser = browserInfo()
    const body = {
      attempt_id: attempt.id,
      recording_id: attempt.recordingId,
      event,
      duration_ms: durationMs,
      metadata_ms: attempt.metadataMs,
      loaded_data_ms: attempt.loadedDataMs,
      canplay_ms: attempt.canplayMs,
      playing_ms: attempt.playingMs,
      browser: browser.browser,
      browser_version: browser.version,
      platform: platformLabel(),
      codec: attempt.codec || 'unknown',
      playback_mode: attempt.playbackMode,
      source_kind: attempt.sourceKind,
      signal,
      hevc_hint: hevcHint(video),
      media_error_code: video.error?.code || undefined,
      ready_state: video.readyState,
      network_state: video.networkState,
    }
    void fetch('/api/playback/metrics/client', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => undefined)
  } catch {
    // Playback telemetry is best effort and must remain invisible to the player.
  }
}

function mediaTarget(event: Event) {
  return event.target instanceof HTMLVideoElement ? event.target : null
}

function onLoadStart(event: Event) {
  const video = mediaTarget(event)
  if (video) startAttempt(video)
}

function onLoadedMetadata(event: Event) {
  const video = mediaTarget(event)
  const attempt = video ? attempts.get(video) : undefined
  if (attempt && attempt.metadataMs === undefined) attempt.metadataMs = elapsed(attempt)
}

function reportFirstFrame(video: HTMLVideoElement, attempt: Attempt, signal: string) {
  if (attempt.firstFrameReported) return
  attempt.firstFrameReported = true
  void report(video, attempt, 'first_frame', elapsed(attempt), signal)
}

function armFrameCallback(video: HTMLVideoElement, attempt: Attempt) {
  if (attempt.firstFrameReported || attempt.frameCallbackArmed) return false
  const callback = video.requestVideoFrameCallback
  if (typeof callback !== 'function') return false
  attempt.frameCallbackArmed = true
  callback.call(video, () => reportFirstFrame(video, attempt, 'video_frame_callback'))
  return true
}

function onLoadedData(event: Event) {
  const video = mediaTarget(event)
  const attempt = video ? attempts.get(video) : undefined
  if (!video || !attempt) return
  if (attempt.loadedDataMs === undefined) attempt.loadedDataMs = elapsed(attempt)
  if (!attempt.decodeReported) {
    attempt.decodeReported = true
    void report(video, attempt, 'decode_ready', attempt.loadedDataMs, 'loadeddata')
  }
  armFrameCallback(video, attempt)
}

function onCanPlay(event: Event) {
  const video = mediaTarget(event)
  const attempt = video ? attempts.get(video) : undefined
  if (!video || !attempt) return
  if (attempt.canplayMs === undefined) attempt.canplayMs = elapsed(attempt)
  armFrameCallback(video, attempt)
}

function onPlaying(event: Event) {
  const video = mediaTarget(event)
  const attempt = video ? attempts.get(video) : undefined
  if (!video || !attempt) return
  if (attempt.playingMs === undefined) attempt.playingMs = elapsed(attempt)
  if (!armFrameCallback(video, attempt) && !attempt.firstFrameReported && !attempt.frameCallbackArmed) {
    reportFirstFrame(video, attempt, 'playing_fallback')
  }
}

function onError(event: Event) {
  const video = mediaTarget(event)
  const attempt = video ? attempts.get(video) : undefined
  if (!video || !attempt || attempt.errorReported) return
  attempt.errorReported = true
  const kind = attempt.firstFrameReported ? 'playback_error' : 'startup_error'
  void report(video, attempt, kind, elapsed(attempt), 'media_error')
}

function listen(name: string, handler: EventListener) {
  document.addEventListener(name, handler, true)
  listeners.push([name, handler])
}

onMounted(() => {
  listen('loadstart', onLoadStart as EventListener)
  listen('loadedmetadata', onLoadedMetadata as EventListener)
  listen('loadeddata', onLoadedData as EventListener)
  listen('canplay', onCanPlay as EventListener)
  listen('playing', onPlaying as EventListener)
  listen('error', onError as EventListener)
})

onBeforeUnmount(() => {
  for (const [name, handler] of listeners) document.removeEventListener(name, handler, true)
  listeners.length = 0
})
</script>

<template><span style="display:none" aria-hidden="true" /></template>
