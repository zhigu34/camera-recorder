import { describe, expect, it } from 'vitest'

import {
  cameraIdFromDetectionQuery,
  countMotionDraftChanges,
  motionDraftFromSource,
  serializeMotionSourcePayload,
} from './event-detection/state'
import type { EventSourceRead, MotionSourceDraft } from './event-detection/types'

const source: EventSourceRead = {
  descriptor: {
    id: 'local.motion',
    provider: 'motion',
    source_kind: 'local',
    status: 'available',
    display_name: '本地移动检测',
    capabilities: ['motion'],
    configurable: true,
    runtime_state: 'running',
    reason: null,
  },
  config: {
    enabled: true,
    sensitivity: 'medium',
    analysis_fps: 5,
    analysis_width: 640,
    min_duration_ms: 800,
    merge_gap_ms: 10_000,
    event_min_interval_ms: 60_000,
  },
  zones: [],
}

describe('event detection pure state', () => {
  it('normalizes camera query ids', () => {
    expect(cameraIdFromDetectionQuery('12')).toBe(12)
    expect(cameraIdFromDetectionQuery(['12'])).toBe(12)
    expect(cameraIdFromDetectionQuery('0')).toBeNull()
    expect(cameraIdFromDetectionQuery('x')).toBeNull()
    expect(cameraIdFromDetectionQuery(null)).toBeNull()
  })

  it('maps local.motion source config into the exact editable draft', () => {
    expect(motionDraftFromSource(source)).toEqual({
      enabled: true,
      sensitivity: 'medium',
      analysis_fps: 5,
      analysis_width: 640,
      min_duration_ms: 800,
      merge_gap_ms: 10_000,
      event_min_interval_ms: 60_000,
    })
  })

  it('counts logical changed motion fields', () => {
    const saved = motionDraftFromSource(source)
    expect(countMotionDraftChanges(saved, saved)).toBe(0)
    expect(countMotionDraftChanges(saved, { ...saved, sensitivity: 'high' })).toBe(1)
    expect(
      countMotionDraftChanges(saved, {
        ...saved,
        enabled: false,
        analysis_fps: 8,
      }),
    ).toBe(2)
  })

  it('serializes only the supported local.motion config fields', () => {
    const draft: MotionSourceDraft = {
      enabled: false,
      sensitivity: 'high',
      analysis_fps: 4,
      analysis_width: 960,
      min_duration_ms: 1200,
      merge_gap_ms: 3000,
      event_min_interval_ms: 90_000,
    }
    expect(serializeMotionSourcePayload(draft)).toEqual(draft)
  })
})
