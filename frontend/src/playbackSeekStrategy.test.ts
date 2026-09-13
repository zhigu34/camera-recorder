import { describe, expect, it } from 'vitest'

import { playbackSeekStrategy } from './utils/playbackSeekStrategy'

describe('playbackSeekStrategy', () => {
  it('seeks in place when the target event belongs to the current recording', () => {
    expect(playbackSeekStrategy(42, 42)).toBe('in-place')
  })

  it('switches recordings when the target event belongs to another recording', () => {
    expect(playbackSeekStrategy(42, 43)).toBe('switch-recording')
  })

  it('switches recordings when there is no active recording yet', () => {
    expect(playbackSeekStrategy(null, 43)).toBe('switch-recording')
  })
})
