import { describe, expect, it } from 'vitest'
import { eventSeekOffset, findMotionRecording, timelineRange } from './utils/motionTimeline'

describe('timelineRange', () => {
  it('maps an event into a percentage range inside the viewport', () => {
    expect(timelineRange(3600, 5400, 0, 86400)).toEqual({ left: 4.1667, width: 2.0833 })
  })

  it('clips events that cross the viewport edges and rejects events outside it', () => {
    expect(timelineRange(-60, 60, 0, 600)).toEqual({ left: 0, width: 10 })
    expect(timelineRange(700, 800, 0, 600)).toBeNull()
  })
})

describe('eventSeekOffset', () => {
  it('seeks two seconds before the motion event relative to its recording', () => {
    expect(eventSeekOffset('2026-09-13T10:00:12+08:00', '2026-09-13T10:00:00+08:00')).toBe(10)
  })

  it('compares deployment wall-clock values even when only one value has an offset', () => {
    expect(eventSeekOffset('2026-09-13T10:00:12', '2026-09-13T10:00:00+08:00')).toBe(10)
  })

  it('never returns a negative seek offset', () => {
    expect(eventSeekOffset('2026-09-13T10:00:01+08:00', '2026-09-13T10:00:00+08:00')).toBe(0)
  })
})

describe('findMotionRecording', () => {
  const recordings = [
    { id: 11, started_at: '2026-09-13T10:00:00+08:00', ended_at: '2026-09-13T10:05:00+08:00' },
    { id: 12, started_at: '2026-09-13T10:05:00+08:00', ended_at: '2026-09-13T10:10:00+08:00' },
  ]

  it('prefers the recording id persisted on the event', () => {
    expect(findMotionRecording({ recording_id: 12, started_at: '2026-09-13T10:02:00' }, recordings)?.id).toBe(12)
  })

  it('falls back to the recording whose wall-clock range contains the event', () => {
    expect(findMotionRecording({ recording_id: null, started_at: '2026-09-13T10:03:00' }, recordings)?.id).toBe(11)
    expect(findMotionRecording({ recording_id: null, started_at: '2026-09-13T11:00:00' }, recordings)).toBeNull()
  })
})
