import { describe, expect, it } from 'vitest'

import {
  availablePackageModes,
  buildExportRequest,
  initialExportRange,
  wallClockIso,
} from './utils/playbackExport'

describe('playback export helpers', () => {
  it('starts a five-minute range at the active wall-clock cursor and clamps to day end', () => {
    expect(initialExportRange(3600, [])).toEqual({ start: 3600, end: 3900 })
    expect(initialExportRange(86300, [])).toEqual({ start: 86300, end: 86400 })
  })

  it('falls back to the first recording start when playback has no active cursor', () => {
    expect(initialExportRange(null, [
      { id: 1, started_at: '2026-09-14T08:12:30+08:00', duration: 600 },
    ])).toEqual({ start: 29550, end: 29850 })
  })

  it('serializes literal wall-clock time with an explicit timezone offset without UTC shifting', () => {
    expect(wallClockIso('2026-09-14', 10 * 3600 + 5 * 60, -480)).toBe('2026-09-14T10:05:00+08:00')
    expect(wallClockIso('2026-09-14', 86400, -480)).toBe('2026-09-15T00:00:00+08:00')
  })

  it('builds the backend request from the selected date and wall-clock range', () => {
    expect(buildExportRequest({
      cameraId: 7,
      date: '2026-09-14',
      range: { start: 3600, end: 4200 },
      exportMode: 'fast',
      gapPolicy: 'split',
      packageMode: 'zip',
      timezoneOffsetMinutes: -480,
    })).toEqual({
      camera_id: 7,
      start_at: '2026-09-14T01:00:00+08:00',
      end_at: '2026-09-14T01:10:00+08:00',
      export_mode: 'fast',
      gap_policy: 'split',
      package_mode: 'zip',
    })
  })

  it('only offers ZIP when a split export actually contains gaps', () => {
    expect(availablePackageModes('merge', true)).toEqual(['individual'])
    expect(availablePackageModes('split', false)).toEqual(['individual'])
    expect(availablePackageModes('split', true)).toEqual(['individual', 'zip'])
  })
})
