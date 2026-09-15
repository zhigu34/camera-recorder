import { describe, expect, it } from 'vitest'
import {
  cameraRoute,
  eventDetectionRoute,
  eventRoute,
  recordingPlaybackRoute,
  settingsSectionRoute,
} from './navigation'

describe('navigation deep links', () => {
  it('targets an exact camera', () => {
    expect(cameraRoute(42)).toEqual({ path: '/cameras', query: { camera_id: '42' } })
  })

  it('targets an exact event', () => {
    expect(eventRoute(9)).toEqual({ path: '/events', query: { event_id: '9' } })
  })

  it('builds an event detection deep link with optional camera context', () => {
    expect(eventDetectionRoute()).toEqual({ path: '/event-detection' })
    expect(eventDetectionRoute(12)).toEqual({
      path: '/event-detection',
      query: { camera_id: '12' },
    })
  })

  it('keeps recording and camera context inside recording management', () => {
    expect(recordingPlaybackRoute(77, 4)).toEqual({
      path: '/recordings/manage',
      query: { recording_id: '77', camera_id: '4' },
    })
  })

  it('targets a settings section', () => {
    expect(settingsSectionRoute('archive')).toEqual({ path: '/settings', query: { section: 'archive' } })
  })
})
