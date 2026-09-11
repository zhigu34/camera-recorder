import axios from 'axios'

export type PlaybackMode = 'original' | 'proxy' | 'proxy-live'
export type HevcHint = 'probably' | 'maybe' | 'unsupported' | 'unknown'

export interface PlaybackMetricContext {
  recordingId: number
  codec: string
  playbackMode: PlaybackMode
  sourceKind: string
  hevcHint: HevcHint
}

interface BrowserInfo {
  browser: string
  browserVersion: string
  platform: string
}

function detectBrowser(): BrowserInfo {
  if (typeof navigator === 'undefined') {
    return { browser: 'unknown', browserVersion: 'unknown', platform: 'unknown' }
  }
  const ua = navigator.userAgent
  let browser = 'unknown'
  let browserVersion = 'unknown'
  const candidates: Array<[string, RegExp]> = [
    ['Edge', /Edg\/(\d+(?:\.\d+)?)/],
    ['Chrome', /(?:Chrome|CriOS)\/(\d+(?:\.\d+)?)/],
    ['Firefox', /(?:Firefox|FxiOS)\/(\d+(?:\.\d+)?)/],
    ['Safari', /Version\/(\d+(?:\.\d+)?).*Safari/],
  ]
  for (const [name, pattern] of candidates) {
    const match = ua.match(pattern)
    if (match) {
      browser = name
      browserVersion = match[1]
      break
    }
  }

  const rawPlatform = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData?.platform || navigator.platform || 'unknown'
  let platform = rawPlatform
  if (/android/i.test(ua)) platform = 'Android'
  else if (/iphone|ipad|ipod/i.test(ua)) platform = 'iOS'
  else if (/win/i.test(rawPlatform)) platform = 'Windows'
  else if (/mac/i.test(rawPlatform)) platform = 'macOS'
  else if (/linux/i.test(rawPlatform)) platform = 'Linux'

  return {
    browser: browser.slice(0, 32),
    browserVersion: browserVersion.slice(0, 16),
    platform: platform.slice(0, 32),
  }
}

export function hevcSupportHint(): HevcHint {
  if (typeof document === 'undefined') return 'unknown'
  const video = document.createElement('video')
  const hvc1 = video.canPlayType('video/mp4; codecs="hvc1"')
  const hev1 = video.canPlayType('video/mp4; codecs="hev1"')
  const hint = hvc1 || hev1
  if (hint === 'probably') return 'probably'
  if (hint === 'maybe') return 'maybe'
  return 'unsupported'
}

export function isBrowserSafeAudio(codec?: string | null): boolean {
  const value = (codec || '').toLowerCase()
  if (!value) return true
  return ['aac', 'mp3'].includes(value)
}

export class PlaybackAttemptTracker {
  private readonly browser = detectBrowser()
  private context: PlaybackMetricContext | null = null
  private attemptId = ''
  private startedAt = 0
  private metadataMs: number | null = null
  private loadedDataMs: number | null = null
  private canplayMs: number | null = null
  private playingMs: number | null = null
  private decodeReported = false
  private firstFrameReported = false
  private firstFramePending = false
  private errorReported = false

  start(context: PlaybackMetricContext) {
    this.context = context
    this.attemptId = `${context.recordingId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    this.startedAt = performance.now()
    this.metadataMs = null
    this.loadedDataMs = null
    this.canplayMs = null
    this.playingMs = null
    this.decodeReported = false
    this.firstFrameReported = false
    this.firstFramePending = false
    this.errorReported = false
  }

  reset() {
    this.context = null
    this.attemptId = ''
    this.firstFramePending = false
  }

  markLoadedMetadata() {
    if (!this.context || this.metadataMs !== null) return
    this.metadataMs = this.elapsed()
  }

  markLoadedData() {
    if (!this.context || this.loadedDataMs !== null) return
    this.loadedDataMs = this.elapsed()
  }

  markCanPlay(video?: HTMLVideoElement | null) {
    if (!this.context) return
    if (this.canplayMs === null) this.canplayMs = this.elapsed()
    if (!this.decodeReported) {
      this.decodeReported = true
      this.report('decode_ready', 'canplay', video)
    }
  }

  markPlaying(video?: HTMLVideoElement | null) {
    if (!this.context || this.firstFrameReported || this.firstFramePending) return
    if (this.playingMs === null) this.playingMs = this.elapsed()
    const candidate = video as (HTMLVideoElement & {
      requestVideoFrameCallback?: (callback: () => void) => number
    }) | null | undefined
    if (candidate?.requestVideoFrameCallback) {
      this.firstFramePending = true
      candidate.requestVideoFrameCallback(() => {
        this.firstFramePending = false
        this.reportFirstFrame('video-frame-callback', candidate)
      })
      return
    }
    this.reportFirstFrame('playing', video)
  }

  markError(video?: HTMLVideoElement | null) {
    if (!this.context || this.errorReported) return
    this.errorReported = true
    this.report(this.firstFrameReported ? 'playback_error' : 'startup_error', 'media-error', video)
  }

  private reportFirstFrame(signal: string, video?: HTMLVideoElement | null) {
    if (!this.context || this.firstFrameReported) return
    this.firstFrameReported = true
    this.report('first_frame', signal, video)
  }

  private elapsed() {
    return Math.max(0, Math.round((performance.now() - this.startedAt) * 10) / 10)
  }

  private report(
    event: 'decode_ready' | 'first_frame' | 'startup_error' | 'playback_error',
    signal: string,
    video?: HTMLVideoElement | null,
  ) {
    const context = this.context
    if (!context || !this.attemptId) return
    const durationMs = this.elapsed()
    const mediaErrorCode = video?.error?.code || null
    void axios.post('/api/playback/metrics/client', {
      attempt_id: this.attemptId,
      recording_id: context.recordingId,
      event,
      duration_ms: durationMs,
      metadata_ms: this.metadataMs,
      loaded_data_ms: this.loadedDataMs,
      canplay_ms: this.canplayMs,
      playing_ms: this.playingMs,
      browser: this.browser.browser,
      browser_version: this.browser.browserVersion,
      platform: this.browser.platform,
      codec: context.codec || 'unknown',
      playback_mode: context.playbackMode,
      source_kind: context.sourceKind || 'unknown',
      signal,
      hevc_hint: context.hevcHint,
      media_error_code: mediaErrorCode,
      ready_state: video?.readyState ?? null,
      network_state: video?.networkState ?? null,
    }).catch(() => undefined)
  }
}
