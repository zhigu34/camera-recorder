import { describe, expect, it } from 'vitest'
import { makePlaybackOpenRequest } from './utils/playbackOpenRequest'

const recording = {
  id: 5,
  camera_id: 2,
  status: 'completed',
  health_status: 'healthy',
  upload_status: 'success',
  warning_count: 0,
  filename: 'a.mp4',
  playback: { state: 'direct' as const, direct: true },
}

describe('playback open request', () => {
  it('clamps negative seek and preserves compatibility intent', () => {
    expect(makePlaybackOpenRequest(recording, -3, true)).toEqual({
      recording,
      seekSeconds: 0,
      forceCompatibility: true,
    })
  })

  it('normalizes non-finite seek to zero', () => {
    expect(makePlaybackOpenRequest(recording, Number.NaN, false).seekSeconds).toBe(0)
  })
})
