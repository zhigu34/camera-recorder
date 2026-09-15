import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

function source(relative: string) {
  const path = fileURLToPath(new URL(relative, import.meta.url))
  return existsSync(path) ? readFileSync(path, 'utf8') : ''
}

describe('health recording gap diagnostics', () => {
  it('shows missing segment count, lost duration and diagnosed causes', () => {
    const table = source('./components/health/CameraReliabilityTable.vue')
    const drawer = source('./components/health/CameraHealthDrawer.vue')
    expect(table).toContain('recording_gap_count')
    expect(table).toContain('missing_recording_seconds')
    expect(table).toContain('缺片段')
    expect(table).toContain('缺失时长')
    expect(drawer).toContain('diagnostics')
    expect(drawer).toContain('cause_label')
    expect(drawer).toContain('诊断详情')
  })
})
