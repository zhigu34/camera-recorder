import { describe, expect, it } from 'vitest'

import cameraHealthDrawerSource from './components/health/CameraHealthDrawer.vue?raw'
import cameraReliabilityTableSource from './components/health/CameraReliabilityTable.vue?raw'

describe('health recording gap diagnostics', () => {
  it('shows missing segment count, lost duration and diagnosed causes', () => {
    const table = cameraReliabilityTableSource
    const drawer = cameraHealthDrawerSource
    expect(table).toContain('recording_gap_count')
    expect(table).toContain('missing_recording_seconds')
    expect(table).toContain('缺片段')
    expect(table).toContain('缺失时长')
    expect(drawer).toContain('diagnostics')
    expect(drawer).toContain('cause_label')
    expect(drawer).toContain('诊断详情')
  })
})