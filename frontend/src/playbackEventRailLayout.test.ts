import { describe, expect, it } from 'vitest'
import eventFeedSource from './PlaybackEventFeed.vue?raw'
import playerSource from './PlaybackPlayer.vue?raw'
import workspaceSource from './PlaybackWorkspace.vue?raw'

describe('Playback detection rail layout', () => {
  it('owns its scrolling layout instead of depending on fixed body heights', () => {
    expect(eventFeedSource).toContain('.playback-event-feed{min-height:0;display:flex;flex-direction:column;overflow:hidden;')
    expect(eventFeedSource).toContain('.event-feed-head{flex:none;')
    expect(eventFeedSource).toContain('.event-filter-row{flex:none;')
    expect(eventFeedSource).toContain('.event-feed-body{min-height:0;flex:1;overflow:auto;')
    expect(eventFeedSource).not.toContain('max-height:360px')
    expect(eventFeedSource).not.toContain('max-height:310px')
  })

  it('uses compact event cards inside the 280px detection rail', () => {
    expect(workspaceSource).toContain('grid-template-columns:160px minmax(0,1fr) 280px')
    expect(eventFeedSource).toContain('grid-template-columns:96px minmax(0,1fr) 10px')
    expect(eventFeedSource).not.toContain('grid-template-columns:150px minmax(0,1fr) 12px')
  })

  it('keeps the playback canvas strict 16:9 and uncropped', () => {
    expect(playerSource).toContain('.player-box{position:relative;aspect-ratio:16/9')
    expect(playerSource).toContain('object-fit:contain')
    expect(playerSource).not.toContain('object-fit:cover')
    expect(playerSource).not.toContain('blur(')
  })
})
