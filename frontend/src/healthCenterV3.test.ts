import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

function source(relative: string) {
  const path = fileURLToPath(new URL(relative, import.meta.url))
  return existsSync(path) ? readFileSync(path, 'utf8') : ''
}

describe('Health Center V3 composition', () => {
  it('puts attention before the reliability matrix and keeps realtime visible', () => {
    const view = source('./HealthCenterView.vue')
    expect(view).toContain('需要关注')
    expect(view).toContain('摄像头可靠性')
    expect(view.indexOf('需要关注')).toBeLessThan(view.indexOf('摄像头可靠性'))
    expect(view).toContain('实时状态')
    expect(view).toContain('24h')
    expect(view).toContain('72h')
  })

  it('provides a diagnostic drawer with evidence and explicit actions', () => {
    const drawer = source('./components/health/CameraHealthDrawer.vue')
    expect(drawer).toContain('原因')
    expect(drawer).toContain('诊断详情')
    expect(drawer).toContain('置信度')
    expect(drawer).toContain('查看回放')
    expect(drawer).toContain('摄像头设置')
  })

  it('uses the V3 route composition without the full playback metrics panel', () => {
    const route = source('./WorkspaceRoute.vue')
    expect(route).toContain("import('./HealthCenterView.vue')")
    expect(route).toContain('<HealthCenterView')
    expect(route).not.toContain('PlaybackMetricsPanel compact')
  })
})
