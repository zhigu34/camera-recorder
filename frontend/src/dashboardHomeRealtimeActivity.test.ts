import { describe, expect, it } from 'vitest'

import dashboardSource from './DashboardView.vue?raw'

describe('dashboard realtime activity semantics', () => {
  it('subscribes to motion.created over the existing events websocket', () => {
    expect(dashboardSource).toContain('/ws/events')
    expect(dashboardSource).toContain('after_motion_id')
    expect(dashboardSource).toContain("message.type === 'motion.created'")
    expect(dashboardSource).toContain('mergeRealtimeActivity')
  })

  it('does not keep the old 20 second polling loop while realtime is healthy', () => {
    expect(dashboardSource).not.toContain('ACTIVITY_REFRESH_MS = 20_000')
    expect(dashboardSource).not.toContain('setInterval(() => void loadActivities(), ACTIVITY_REFRESH_MS)')
    expect(dashboardSource).toContain('ACTIVITY_FALLBACK_REFRESH_MS')
    expect(dashboardSource).toContain("activitySocketState.value === 'connected'")
  })

  it('pauses realtime work while hidden and resyncs when the page becomes visible again', () => {
    expect(dashboardSource).toContain("document.addEventListener('visibilitychange'")
    expect(dashboardSource).toContain('document.hidden')
    expect(dashboardSource).toContain('handleVisibilityChange')
    expect(dashboardSource).toContain('void loadActivities()')
  })

  it('keeps realtime updates passive and marks fresh cards without auto-starting media', () => {
    expect(dashboardSource).toContain('freshActivityIds')
    expect(dashboardSource).toContain("'activity-card fresh'")
    expect(dashboardSource).not.toContain('/ws/preview-wall')
    expect(dashboardSource).toContain('camera-recorder:playback-event-autostart')
  })

  it('uses explicit unknown connectivity wording and surfaces the observation source', () => {
    expect(dashboardSource).toContain("return '状态未知'")
    expect(dashboardSource).toContain('connectivitySourceLabel')
    expect(dashboardSource).toContain('connectivity_source')
  })
})
