import { describe, expect, it } from 'vitest'

import serviceStripSource from './HealthServiceStrip.vue?raw'

describe('Health service strip', () => {
  it('loads compact playback health while mounted without embedding the full compatibility matrix', () => {
    expect(serviceStripSource).toContain("'/api/playback/metrics'")
    expect(serviceStripSource).toContain('60_000')
    expect(serviceStripSource).toContain('首帧成功率')
    expect(serviceStripSource).toContain('首帧 P95')
    expect(serviceStripSource).toContain('启动失败')
    expect(serviceStripSource).toContain('兼容异常组')
    expect(serviceStripSource).not.toContain('<el-table')
  })
})