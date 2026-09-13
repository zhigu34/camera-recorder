import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const source = readFileSync(fileURLToPath(new URL('./PlaybackWorkspace.vue', import.meta.url)), 'utf8')

describe('Playback desktop viewport layout', () => {
  it('keeps the desktop playback workspace inside the application viewport', () => {
    expect(source).toContain('@media(min-width:1101px)')
    expect(source).toContain('height:calc(100dvh - 131px)')
    expect(source).toContain('grid-template-rows:auto minmax(0,1fr) auto')
    expect(source).toContain('.playback-main-grid{min-height:0')
    expect(source).toContain(':deep(.playback-player .player-box){height:100%;min-height:260px;aspect-ratio:auto}')
    expect(source).toContain(':deep(.playback-event-feed .event-feed-body){max-height:none;min-height:0;flex:1}')
  })
})
