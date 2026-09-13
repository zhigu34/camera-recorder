import { describe, expect, it } from 'vitest'

import {
  motionEventDuration,
  motionEventSeekTarget,
  motionEventSnapshotUrl,
  motionEventZoneLabel,
  prepareMotionEventFeed,
} from './utils/motionEventFeed'

const recordings = [
  {
    id: 10,
    started_at: '2026-09-13T16:20:00+08:00',
    ended_at: '2026-09-13T16:25:00+08:00',
    duration: 300,
  },
]

const events = [
  {
    id: 1,
    camera_id: 2,
    zone_id: 7,
    recording_id: 10,
    started_at: '2026-09-13T16:21:10+08:00',
    ended_at: '2026-09-13T16:21:18+08:00',
    snapshot_path: 'motion/a.jpg',
  },
  {
    id: 2,
    camera_id: 2,
    zone_id: null,
    recording_id: null,
    started_at: '2026-09-13T16:28:00+08:00',
    ended_at: '2026-09-13T16:28:04+08:00',
    snapshot_path: null,
  },
  {
    id: 3,
    camera_id: 2,
    zone_id: null,
    recording_id: 10,
    started_at: '2026-09-13T16:24:30+08:00',
    ended_at: '2026-09-13T16:24:35+08:00',
    snapshot_path: null,
  },
]

describe('prepareMotionEventFeed', () => {
  it('keeps only events with playable recording coverage and sorts newest first', () => {
    expect(prepareMotionEventFeed(events, recordings).map((event) => event.id)).toEqual([3, 1])
  })
})

describe('motion event display helpers', () => {
  it('calculates event duration in seconds', () => {
    expect(motionEventDuration(events[0])).toBe(8)
  })

  it('jumps two seconds before the event and clamps at midnight', () => {
    expect(motionEventSeekTarget(events[0])).toBe(16 * 3600 + 21 * 60 + 8)
    expect(motionEventSeekTarget({ ...events[0], started_at: '2026-09-13T00:00:01+08:00' })).toBe(0)
  })

  it('uses the saved zone name and falls back to full frame', () => {
    const zones = [{ id: 7, name: '东门区域' }]
    expect(motionEventZoneLabel(events[0], zones)).toBe('东门区域')
    expect(motionEventZoneLabel(events[2], zones)).toBe('全画面')
  })

  it('builds the snapshot endpoint from the event id', () => {
    expect(motionEventSnapshotUrl(events[0])).toBe('/api/motion-events/1/snapshot')
  })
})
