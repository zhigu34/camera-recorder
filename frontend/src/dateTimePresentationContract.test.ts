import { describe, expect, it } from 'vitest'

const sources = import.meta.glob('./**/*.{ts,vue}', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>

function productionSources() {
  return Object.entries(sources).filter(([path]) =>
    !path.endsWith('.test.ts') && !path.endsWith('/utils/dateTime.ts'),
  )
}

describe('complete datetime presentation policy', () => {
  it('does not format complete datetimes with the browser local timezone', () => {
    const offenders = productionSources()
      .filter(([, source]) => source.includes('.toLocaleString('))
      .map(([path]) => path)
      .sort()

    expect(offenders, `browser-local datetime formatting remains in:\n${offenders.join('\n')}`).toEqual([])
  })

  it('does not keep duplicated Date-based local complete-datetime formatters', () => {
    const localFormatterPattern = /function\s+(?:formatTime|lastCheckText)\s*\([^)]*\)\s*\{[\s\S]{0,500}?new Date\(/m
    const offenders = productionSources()
      .filter(([, source]) => localFormatterPattern.test(source))
      .map(([path]) => path)
      .sort()

    expect(offenders, `duplicated Date-based datetime formatters remain in:\n${offenders.join('\n')}`).toEqual([])
  })

  it('preserves pure-clock and date-grouping business helpers', () => {
    expect(sources['./PlaybackEventFeed.vue']).toContain('function clockLabel')
    expect(sources['./RecordingManagementView.vue']).toContain('function localSeconds')
    expect(sources['./EventCenterView.vue']).toContain('function activityDayLabel')
  })
})
