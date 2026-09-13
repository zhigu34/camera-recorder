import { describe, expect, it } from 'vitest'
import mainSource from './main.ts?raw'
import playerSource from './PlaybackPlayer.vue?raw'
import densityStyles from './styles/playback-workspace-density.css?raw'

describe('Playback visual density', () => {
  it('loads the playback workspace density layer', () => {
    expect(mainSource).toContain("import './styles/playback-workspace-density.css'")
  })

  it('unifies the player surface without changing video fitting policy', () => {
    expect(densityStyles).toContain('.playback-workspace .playback-video-panel.playback-video-panel')
    expect(densityStyles).toContain('padding: 0;')
    expect(densityStyles).toContain('.playback-workspace .playback-video-panel .playback-player .player-box')
    expect(densityStyles).toContain('border: 0;')
    expect(densityStyles).toContain('border-radius: 0;')
    expect(playerSource).toContain('aspect-ratio:16/9')
    expect(playerSource).toContain('object-fit:contain')
    expect(playerSource).not.toContain('object-fit:cover')
    expect(playerSource).not.toContain('filter:blur')
  })

  it('compresses the timeline while keeping the playhead prominent', () => {
    expect(densityStyles).toContain('--timeline-label-width: 52px;')
    expect(densityStyles).toContain('height: 19px;')
    expect(densityStyles).toContain('min-height: 22px;')
    expect(densityStyles).toContain('height: 13px;')
    expect(densityStyles).toContain('.playback-workspace .playback-v3 .timeline-playhead::after')
    expect(densityStyles).toContain('width: 2px;')
  })
})
