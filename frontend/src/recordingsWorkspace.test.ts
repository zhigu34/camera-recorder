import { describe, expect, it } from 'vitest'
import { recordingModeFromMeta, recordingTabLocation } from './utils/recordingsWorkspace'

describe('recordings workspace', () => {
  it('defaults unknown mode to playback', () => {
    expect(recordingModeFromMeta(undefined)).toBe('playback')
    expect(recordingModeFromMeta('manage')).toBe('manage')
  })

  it('preserves query and hash across tabs', () => {
    const query = { camera_id: '7', date: '2026-09-13', recording_id: '91' }
    expect(recordingTabLocation('manage', query, '#playback-compatibility')).toEqual({
      path: '/recordings/manage', query, hash: '#playback-compatibility',
    })
    expect(recordingTabLocation('playback', query, '')).toEqual({
      path: '/recordings/playback', query, hash: '',
    })
  })
})
