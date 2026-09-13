import { isBrowserSafeAudio, type HevcHint } from './playbackCompatibility'

export type PlaybackSourceMode = 'original' | 'compatibility'
export type PlaybackSourceReason =
  | 'direct'
  | 'forced'
  | 'hevc-unsupported'
  | 'audio-incompatible'
  | 'video-incompatible'

export interface PlaybackSourceInput {
  videoCodec?: string | null
  audioCodec?: string | null
  hevcHint: HevcHint
  forceCompatibility?: boolean
}

export interface PlaybackSourceDecision {
  mode: PlaybackSourceMode
  reason: PlaybackSourceReason
}

function normalizeCodec(codec?: string | null) {
  return (codec || '').trim().toLowerCase()
}

export function choosePlaybackSource(input: PlaybackSourceInput): PlaybackSourceDecision {
  if (input.forceCompatibility) return { mode: 'compatibility', reason: 'forced' }

  const videoCodec = normalizeCodec(input.videoCodec)
  const isH264 = videoCodec === 'h264' || videoCodec === 'avc' || videoCodec === 'avc1'
  const isHevc = videoCodec === 'hevc' || videoCodec === 'h265' || videoCodec === 'hev1' || videoCodec === 'hvc1'

  if (isHevc && input.hevcHint === 'unsupported') {
    return { mode: 'compatibility', reason: 'hevc-unsupported' }
  }

  if (!isBrowserSafeAudio(input.audioCodec)) {
    return { mode: 'compatibility', reason: 'audio-incompatible' }
  }

  if (!isH264 && !isHevc) {
    return { mode: 'compatibility', reason: 'video-incompatible' }
  }

  return { mode: 'original', reason: 'direct' }
}
