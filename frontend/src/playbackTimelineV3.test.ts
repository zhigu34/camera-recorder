import { describe, expect, it } from 'vitest'
import {
  ZOOM_SPANS,
  clampViewport,
  findRecordingAtWallTime,
  motionEventOverlapsRecordings,
  motionPlaybackStartSeconds,
  moveTimelineRange,
  normalizeTimelineRange,
  rangePercent,
  recordingSeekOffset,
  resizeTimelineRange,
  timeAtPointer,
  timeAtTrackPointer,
  zoomAround,
} from './utils/playbackTimelineV3'

describe('Playback V3 zoom spans', () => {
  it('uses the four approved zoom levels', () => {
    expect(ZOOM_SPANS).toEqual({ '24h': 86400, '6h': 21600, '1h': 3600, '15m': 900 })
  })
})

describe('clampViewport', () => {
  it('keeps a viewport inside a single day', () => {
    expect(clampViewport(-300, 3600)).toBe(0)
    expect(clampViewport(85000, 3600)).toBe(82800)
    expect(clampViewport(3600, 3600)).toBe(3600)
  })
})

describe('timeAtPointer', () => {
  it('maps pointer position into wall-clock seconds', () => {
    expect(timeAtPointer(3600, 3600, 0)).toBe(3600)
    expect(timeAtPointer(3600, 3600, 0.5)).toBe(5400)
    expect(timeAtPointer(3600, 3600, 1)).toBe(7200)
  })
})

describe('motion event playback target', () => {
  it('starts two seconds before the detected motion', () => {
    expect(motionPlaybackStartSeconds('2026-09-13T10:00:05+08:00')).toBe(10 * 3600 + 3)
  })

  it('clamps preroll at the beginning of the day', () => {
    expect(motionPlaybackStartSeconds('2026-09-13T00:00:01+08:00')).toBe(0)
  })
})

describe('timeAtTrackPointer', () => {
  it('uses only the actual time track bounds and ignores the label column', () => {
    const viewStart = 16 * 3600 + 20 * 60 + 55
    const viewSpan = 8 * 60
    const trackLeft = 160
    const trackWidth = 1740

    expect(timeAtTrackPointer(viewStart, viewSpan, trackLeft + trackWidth * 0.75, trackLeft, trackWidth))
      .toBe(16 * 3600 + 26 * 60 + 55)
  })

  it('clamps clicks outside the time track to the visible window', () => {
    expect(timeAtTrackPointer(3600, 900, 50, 100, 1000)).toBe(3600)
    expect(timeAtTrackPointer(3600, 900, 1200, 100, 1000)).toBe(4500)
  })
})

describe('rangePercent', () => {
  it('clips recording ranges to the visible viewport', () => {
    expect(rangePercent(3300, 3900, 3600, 3600)).toEqual({ left: 0, width: 8.3333 })
    expect(rangePercent(6900, 7500, 3600, 3600)).toEqual({ left: 91.6667, width: 8.3333 })
    expect(rangePercent(8000, 9000, 3600, 3600)).toBeNull()
  })
})

describe('timeline export range helpers', () => {
  it('orders reversed endpoints and clamps to the day', () => {
    expect(normalizeTimelineRange(90000, -20)).toEqual({ start: 0, end: 86400 })
    expect(normalizeTimelineRange(4200, 3600)).toEqual({ start: 3600, end: 4200 })
  })

  it('enforces a minimum duration while keeping the range inside the day', () => {
    expect(normalizeTimelineRange(100, 105, 30)).toEqual({ start: 100, end: 130 })
    expect(normalizeTimelineRange(86390, 86400, 30)).toEqual({ start: 86370, end: 86400 })
  })

  it('resizes either edge without crossing the minimum duration', () => {
    const range = { start: 3600, end: 4200 }
    expect(resizeTimelineRange(range, 'start', 4100, 60)).toEqual({ start: 4100, end: 4200 })
    expect(resizeTimelineRange(range, 'start', 4190, 60)).toEqual({ start: 4140, end: 4200 })
    expect(resizeTimelineRange(range, 'end', 3650, 60)).toEqual({ start: 3600, end: 3660 })
    expect(resizeTimelineRange(range, 'end', 4500, 60)).toEqual({ start: 3600, end: 4500 })
  })

  it('moves the whole range while preserving duration at day boundaries', () => {
    expect(moveTimelineRange({ start: 100, end: 400 }, -500)).toEqual({ start: 0, end: 300 })
    expect(moveTimelineRange({ start: 86000, end: 86300 }, 500)).toEqual({ start: 86100, end: 86400 })
    expect(moveTimelineRange({ start: 3600, end: 4200 }, 90)).toEqual({ start: 3690, end: 4290 })
  })
})

describe('zoomAround', () => {
  it('keeps the anchor time stable while zooming when possible', () => {
    expect(zoomAround(0, 86400, 21600, 0.5)).toBe(32400)
    expect(zoomAround(32400, 21600, 3600, 0.5)).toBe(41400)
  })

  it('clamps near day boundaries', () => {
    expect(zoomAround(0, 21600, 3600, 0)).toBe(0)
    expect(zoomAround(64800, 21600, 3600, 1)).toBe(82800)
  })
})

describe('findRecordingAtWallTime', () => {
  const recordings = [
    { id: 1, started_at: '2026-09-13T10:00:00+08:00', ended_at: '2026-09-13T10:10:00+08:00', duration: 600 },
    { id: 2, started_at: '2026-09-13T10:20:00+08:00', ended_at: null, duration: 300 },
  ]

  it('returns the segment containing the requested deployment wall-clock time', () => {
    expect(findRecordingAtWallTime(recordings, 10 * 3600 + 5 * 60)?.id).toBe(1)
    expect(findRecordingAtWallTime(recordings, 10 * 3600 + 22 * 60)?.id).toBe(2)
  })

  it('returns null for a recording gap', () => {
    expect(findRecordingAtWallTime(recordings, 10 * 3600 + 15 * 60)).toBeNull()
  })
})

describe('recordingSeekOffset', () => {
  it('uses the actual recording range when duration metadata is missing or zero', () => {
    expect(recordingSeekOffset({
      id: 7,
      started_at: '2026-09-13T10:00:00+08:00',
      ended_at: '2026-09-13T10:10:00+08:00',
      duration: 0,
    }, 10 * 3600 + 30)).toBe(30)
  })
})

describe('motionEventOverlapsRecordings', () => {
  const recordings = [
    {
      id: 1,
      started_at: '2026-09-13T16:20:55+08:00',
      ended_at: '2026-09-13T16:24:55+08:00',
      duration: 240,
    },
  ]

  it('keeps motion events that have playable recording coverage', () => {
    expect(motionEventOverlapsRecordings({
      started_at: '2026-09-13T16:22:00+08:00',
      ended_at: '2026-09-13T16:22:05+08:00',
    }, recordings)).toBe(true)
  })

  it('rejects motion events that fall entirely inside a recording gap', () => {
    expect(motionEventOverlapsRecordings({
      started_at: '2026-09-13T16:26:55+08:00',
      ended_at: '2026-09-13T16:27:00+08:00',
    }, recordings)).toBe(false)
  })
})
