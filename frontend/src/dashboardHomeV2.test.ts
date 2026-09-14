import { describe, expect, it } from 'vitest'

import dashboardSource from './DashboardView.vue?raw'
import previewSource from './PreviewViewV2.vue?raw'

describe('dashboard protect home v2 semantics', () => {
  it('uses motion activity snapshots as the home attention feed without opening live preview sockets', () => {
    expect(dashboardSource).toContain("'/api/motion-events'")
    expect(dashboardSource).toContain('/api/motion-events/${event.id}/snapshot')
    expect(dashboardSource).toContain('最近活动')
    expect(dashboardSource).not.toContain('/api/events?limit=8')
    expect(dashboardSource).not.toContain('/ws/preview-wall')
  })

  it('treats a home activity click as explicit playback intent', () => {
    expect(dashboardSource).toContain('camera-recorder:playback-event-autostart')
    expect(dashboardSource).toContain("path: '/recordings/playback'")
    expect(dashboardSource).toContain('wall_seconds')
  })

  it('primes Live camera context through its saved wall without starting media', () => {
    expect(dashboardSource).toContain('nvr-video-wall-v1')
    expect(dashboardSource).toContain("path: '/preview'")
    expect(dashboardSource).toContain('primeLiveCamera')
    expect(previewSource).toContain('loadSavedWall()')
    expect(previewSource).toContain('function startSlot(index: number)')
    expect(previewSource).toContain('void loadData()')
  })
})
