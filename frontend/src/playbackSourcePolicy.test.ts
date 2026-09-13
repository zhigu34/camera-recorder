import { describe, expect, it } from 'vitest'
import { choosePlaybackSource } from './utils/playbackSourcePolicy'

describe('playback source policy', () => {
  it('keeps browser-safe H.264 and HEVC on original playback', () => {
    expect(choosePlaybackSource({ videoCodec: 'h264', audioCodec: 'aac', hevcHint: 'unknown' })).toEqual({ mode: 'original', reason: 'direct' })
    expect(choosePlaybackSource({ videoCodec: 'hevc', audioCodec: 'aac', hevcHint: 'maybe' })).toEqual({ mode: 'original', reason: 'direct' })
  })

  it('uses compatibility playback when HEVC is explicitly unsupported', () => {
    expect(choosePlaybackSource({ videoCodec: 'hevc', audioCodec: 'aac', hevcHint: 'unsupported' })).toEqual({ mode: 'compatibility', reason: 'hevc-unsupported' })
  })

  it('uses compatibility playback for unsafe audio or unsupported video codecs', () => {
    expect(choosePlaybackSource({ videoCodec: 'h264', audioCodec: 'pcm_alaw', hevcHint: 'unknown' })).toEqual({ mode: 'compatibility', reason: 'audio-incompatible' })
    expect(choosePlaybackSource({ videoCodec: 'mpeg4', audioCodec: 'aac', hevcHint: 'unknown' })).toEqual({ mode: 'compatibility', reason: 'video-incompatible' })
  })

  it('honors a manual compatibility request', () => {
    expect(choosePlaybackSource({ videoCodec: 'h264', audioCodec: 'aac', hevcHint: 'unknown', forceCompatibility: true })).toEqual({ mode: 'compatibility', reason: 'forced' })
  })
})
