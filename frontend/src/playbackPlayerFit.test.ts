import { describe, expect, it } from 'vitest'
import source from './PlaybackPlayer.vue?raw'

describe('Playback player adaptive fit', () => {
  it('keeps the foreground video contained while filling side bars with a blurred background video', () => {
    expect(source).toContain('class="player-backdrop"')
    expect(source).toContain('class="player-video"')
    expect(source).toContain('.player-video{')
    expect(source).toContain('object-fit:contain')
    expect(source).toContain('.player-backdrop{')
    expect(source).toContain('object-fit:cover')
    expect(source).toContain('filter:blur(')
    expect(source).toContain('pointer-events:none')
  })
})
