import { describe, expect, it } from 'vitest'

import healthCenterViewSource from './HealthCenterView.vue?raw'
import cameraHealthDrawerSource from './components/health/CameraHealthDrawer.vue?raw'
import workspaceRouteSource from './WorkspaceRoute.vue?raw'

describe('Health Center V3 composition', () => {
  it('puts attention before the reliability matrix and keeps realtime visible', () => {
    const view = healthCenterViewSource
    expect(view).toContain('需要关注')
    expect(view).toContain('摄像头可靠性')
    expect(view.indexOf('需要关注')).toBeLessThan(view.indexOf('摄像头可靠性'))
    expect(view).toContain('实时状态')
    expect(view).toContain('24h')
    expect(view).toContain('72h')
  })

  it('provides a diagnostic drawer with evidence and explicit actions', () => {
    const drawer = cameraHealthDrawerSource
    expect(drawer).toContain('原因')
    expect(drawer).toContain('诊断详情')
    expect(drawer).toContain('置信度')
    expect(drawer).toContain('查看回放')
    expect(drawer).toContain('摄像头设置')
  })

  it('uses the V3 route composition without the full playback metrics panel', () => {
    const route = workspaceRouteSource
    expect(route).toContain("import('./HealthCenterView.vue')")
    expect(route).toContain('<HealthCenterView')
    expect(route).not.toContain('PlaybackMetricsPanel compact')
  })
})