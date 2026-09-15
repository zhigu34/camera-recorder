import { describe, expect, it } from 'vitest'

import healthSource from './HealthView.vue?raw'

describe('health recording gap diagnostics', () => {
  it('shows missing segment count, lost duration and diagnosed causes', () => {
    expect(healthSource).toContain('recording_gap_count')
    expect(healthSource).toContain('missing_recording_seconds')
    expect(healthSource).toContain('gap_diagnostics')
    expect(healthSource).toContain('缺片段')
    expect(healthSource).toContain('缺失时长')
  })
})
