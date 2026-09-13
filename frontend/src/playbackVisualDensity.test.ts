import { describe, expect, it } from 'vitest'
import mainSource from './main.ts?raw'
import playerSource from './PlaybackPlayer.vue?raw'

describe('Playback visual density', () => {
  it('loads the playback workspace density layer', () => {
    expect(mainSource).toContain("import './styles/playback-workspace-density.css'")
  })

  it('keeps the player fitting policy unchanged while visual refinements are applied', () => {
    expect(playerSource).toContain('aspect-ratio:16/9')
    expect(playerSource).toContain('object-fit:contain')
    expect(playerSource).not.toContain('object-fit:cover')
    expect(playerSource).not.toContain('filter:blur')
  })
})
