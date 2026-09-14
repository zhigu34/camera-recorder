import { describe, expect, it } from 'vitest'
import eventCenterSource from './EventCenterView.vue?raw'
import playbackSource from './PlaybackWorkspace.vue?raw'

describe('activity center v2 semantics', () => {
  it('defaults the event center to a visual motion activity stream while preserving system events', () => {
    expect(eventCenterSource).toContain('activity-center-view')
    expect(eventCenterSource).toContain('system-event-view')
    expect(eventCenterSource).toContain('/api/motion-events')
    expect(eventCenterSource).toContain('活动')
    expect(eventCenterSource).toContain('系统事件')
    expect(eventCenterSource).toContain('activity-card')
    expect(eventCenterSource).toContain('activity-day-group')
  })

  it('opens an activity at its exact playback wall-clock position through a one-shot explicit action', () => {
    expect(eventCenterSource).toContain('camera-recorder:playback-event-autostart')
    expect(eventCenterSource).toContain("path: '/recordings/playback'")
    expect(eventCenterSource).toContain('wall_seconds')
    expect(eventCenterSource).toContain('event_id')

    expect(playbackSource).toContain('camera-recorder:playback-event-autostart')
    expect(playbackSource).toContain('wall_seconds')
    expect(playbackSource).toContain('event_id')
  })
})
