import { describe, expect, it } from 'vitest'

import panelSource from './MotionDetectionPanel.vue?raw'

function templateSource() {
  const match = panelSource.match(/<template>([\s\S]*?)<\/template>/)
  return match?.[1] || ''
}

describe('MotionDetectionPanel V2 runtime UI', () => {
  it('maps detector phases to user-facing runtime labels', () => {
    expect(panelSource).toContain("if (state === 'warming_up') return '背景学习中'")
    expect(panelSource).toContain("if (state === 'stabilizing') return '画面稳定中'")
    expect(panelSource).toContain("if (state === 'running') return '检测中'")
    expect(panelSource).toContain('.runtime-pill.warming_up i')
    expect(panelSource).toContain('.runtime-pill.stabilizing i')
  })

  it('renders compact read-only diagnostics instead of new tuning controls', () => {
    const template = templateSource()

    expect(template).toContain('class="runtime-diagnostics"')
    expect(template).toContain('状态')
    expect(template).toContain('置信度')
    expect(template).toContain('活动区域')
    expect(template).toContain('画面变化')
    expect(template).toContain('最近帧')
    expect(template).toContain('{{ confidenceLabel }}')
    expect(template).toContain('{{ activeZoneLabel }}')
    expect(template).toContain('{{ imageChangeLabel }}')

    expect(template).not.toContain('min_zone_overlap_ratio')
    expect(template).not.toContain('global_change_ratio')
    expect(template).not.toContain('enter_confidence')
    expect(template).not.toContain('exit_confidence')
  })

  it('formats confidence, active zone and global-change diagnostics', () => {
    expect(panelSource).toContain('Math.round(value * 100)')
    expect(panelSource).toContain("return `${Math.round(value * 100)}%`")
    expect(panelSource).toContain("return zone?.name || '整个画面'")
    expect(panelSource).toContain("? '全局变化抑制' : '正常'")
  })

  it('keeps the existing user controls and whole-frame semantics', () => {
    const template = templateSource()
    expect(template).toContain('灵敏度')
    expect(template).toContain('分析帧率')
    expect(template).toContain('最短移动时间')
    expect(template).toContain('连续活动合并')
    expect(template).toContain('事件最小间隔')
    expect(template).toContain('没有启用检测区域时，默认检测整个画面')
  })
})
