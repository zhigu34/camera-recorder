import { describe, expect, it } from 'vitest'
import workspaceSource from './PlaybackWorkspace.vue?raw'
import eventFeedSource from './PlaybackEventFeed.vue?raw'

describe('Playback desktop viewport layout', () => {
  it('uses narrow side columns around a strict 16:9 player', () => {
    expect(workspaceSource).toContain('class="playback-sidebar"')
    expect(workspaceSource).toContain('class="playback-camera-list"')
    expect(workspaceSource).toContain('class="camera-status-dot"')
    expect(workspaceSource).not.toContain('class="playback-context-bar"')
    expect(workspaceSource).toContain('grid-template-columns:160px minmax(0,1fr) 280px')
    expect(workspaceSource).toContain(':deep(.playback-player .player-box){width:100%;aspect-ratio:16/9}')
    expect(eventFeedSource).toContain('grid-template-columns:150px minmax(0,1fr) 12px')
  })

  it('sizes both side panels from the middle player panel height', () => {
    expect(workspaceSource).toContain('class="playback-side-slot playback-left-slot"')
    expect(workspaceSource).toContain('class="playback-side-slot playback-events-slot"')
    expect(workspaceSource).toContain('.playback-side-slot{position:relative;min-width:0;min-height:0}')
    expect(workspaceSource).toContain('.playback-left-slot>.playback-sidebar{position:absolute;inset:0}')
    expect(workspaceSource).toContain('.playback-events-slot :deep(.playback-event-feed){position:absolute;inset:0')
    expect(workspaceSource).toContain(':deep(.playback-event-feed .event-feed-body){max-height:none;min-height:0;flex:1}')
  })

  it('keeps the desktop playback workspace inside the application viewport', () => {
    expect(workspaceSource).toContain('@media(min-width:1101px)')
    expect(workspaceSource).toContain('height:calc(100dvh - 131px)')
    expect(workspaceSource).toContain('grid-template-rows:minmax(0,1fr) auto')
    expect(workspaceSource).toContain('.playback-main-grid{min-height:0')
  })
})