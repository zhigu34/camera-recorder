import { beforeEach, describe, expect, it } from 'vitest'

import {
  applicationTimeZone,
  configureApplicationTimeZone,
  formatDateTime,
} from './utils/dateTime'

beforeEach(() => configureApplicationTimeZone('Asia/Shanghai'))

describe('application datetime presentation', () => {
  it('renders a UTC instant in Asia/Shanghai', () => {
    expect(formatDateTime('2026-09-14T17:01:01Z')).toBe('2026-09-15 01:01:01')
  })

  it('renders an offset-aware instant without double shifting', () => {
    expect(formatDateTime('2026-09-15T01:01:01+08:00')).toBe('2026-09-15 01:01:01')
  })

  it('passes through an existing backend display datetime unchanged', () => {
    expect(formatDateTime('2026-09-15 01:01:01')).toBe('2026-09-15 01:01:01')
  })

  it('treats a naive ISO API datetime as UTC for presentation', () => {
    expect(formatDateTime('2026-09-14T17:01:01')).toBe('2026-09-15 01:01:01')
  })

  it('returns dash for empty values and original text for invalid non-empty values', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })

  it('rejects invalid frontend timezone configuration with Shanghai fallback', () => {
    expect(configureApplicationTimeZone('Invalid/Timezone')).toBe('Asia/Shanghai')
    expect(applicationTimeZone()).toBe('Asia/Shanghai')
  })
})
