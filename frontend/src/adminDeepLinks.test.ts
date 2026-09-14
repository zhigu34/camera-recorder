import { describe, expect, it } from 'vitest'
import {
  archiveSettingsLocation,
  parsePositiveQueryId,
  uploadTaskLocation,
} from './utils/adminDeepLinks'

describe('admin entity deep links', () => {
  it('opens a specific upload task without losing the upload workspace', () => {
    expect(uploadTaskLocation(42)).toEqual({
      path: '/uploads',
      query: { task_id: '42' },
    })
  })

  it('opens archive settings through the canonical settings query', () => {
    expect(archiveSettingsLocation()).toEqual({
      path: '/settings',
      query: { section: 'archive' },
    })
  })

  it('accepts only positive integer entity ids from route queries', () => {
    expect(parsePositiveQueryId('7')).toBe(7)
    expect(parsePositiveQueryId(['9', '10'])).toBe(9)
    expect(parsePositiveQueryId('0')).toBeNull()
    expect(parsePositiveQueryId('-2')).toBeNull()
    expect(parsePositiveQueryId('oops')).toBeNull()
  })
})
