import { describe, expect, it } from 'vitest'
import { recordingSeekOffset } from './utils/playbackTimelineV3'

describe('recordingSeekOffset', () => {
  it('calculates the seek offset from deployment wall-clock seconds', () => {
    const recording = { id: 1, started_at: '2026-09-13T14:30:00+08:00', duration: 600 }
    expect(recordingSeekOffset(recording, 14 * 3600 + 38 * 60 + 27)).toBe(507)
  })

  it('never seeks outside the recording duration', () => {
    const recording = { id: 1, started_at: '2026-09-13T14:30:00+08:00', duration: 600 }
    expect(recordingSeekOffset(recording, 14 * 3600 + 20 * 60)).toBe(0)
    expect(recordingSeekOffset(recording, 14 * 3600 + 45 * 60)).toBe(600)
  })
})
