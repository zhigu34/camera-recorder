import { describe, expect, it } from 'vitest'

import {
  isActiveTileState,
  shouldResumeAfterVisibility,
  tilePrimaryAction,
  tilePrimaryLabel,
} from './utils/previewTileState'

describe('live preview tile state', () => {
  it('maps every tile state to one primary media action', () => {
    expect(tilePrimaryAction('idle')).toBe('start')
    expect(tilePrimaryAction('connecting')).toBe('pause')
    expect(tilePrimaryAction('playing')).toBe('pause')
    expect(tilePrimaryAction('paused')).toBe('resume')
    expect(tilePrimaryAction('retrying')).toBe('pause')
    expect(tilePrimaryAction('error')).toBe('retry')
    expect(tilePrimaryLabel('playing')).toBe('暂停')
  })

  it('resumes after tab visibility only when the user had started an active tile', () => {
    expect(shouldResumeAfterVisibility(true, true)).toBe(true)
    expect(shouldResumeAfterVisibility(false, true)).toBe(false)
    expect(shouldResumeAfterVisibility(true, false)).toBe(false)
  })

  it('treats only connecting, playing, and retrying as active media states', () => {
    expect(isActiveTileState('connecting')).toBe(true)
    expect(isActiveTileState('playing')).toBe(true)
    expect(isActiveTileState('retrying')).toBe(true)
    expect(isActiveTileState('idle')).toBe(false)
    expect(isActiveTileState('paused')).toBe(false)
    expect(isActiveTileState('error')).toBe(false)
  })
})
