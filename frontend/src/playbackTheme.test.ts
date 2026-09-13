import { describe, expect, it } from 'vitest'
import eventFeedSource from './PlaybackEventFeed.vue?raw'
import timelineSource from './PlaybackTimelineV3.vue?raw'
import workspaceSource from './PlaybackWorkspace.vue?raw'

describe('Playback theme contrast', () => {
  it('uses theme tokens for timeline surfaces and separators', () => {
    expect(timelineSource).toContain('background:var(--nvr-surface)')
    expect(timelineSource).toContain('border-bottom:1px solid var(--nvr-border)')
    expect(timelineSource).toContain('.lane-track{position:relative;margin:6px 0;background:var(--nvr-input)')
    expect(timelineSource).toContain('.timeline-overview{position:relative;height:18px;margin:10px 0 0 var(--timeline-label-width);border:1px solid var(--nvr-border);border-radius:4px;background:var(--nvr-input)')
  })

  it('does not rely on the undefined nvr-bg-soft token', () => {
    expect(workspaceSource).not.toContain('var(--nvr-bg-soft)')
    expect(eventFeedSource).not.toContain('var(--nvr-bg-soft)')
    expect(timelineSource).not.toContain('var(--nvr-bg-soft)')
  })

  it('keeps active controls and playhead readable in both themes', () => {
    expect(eventFeedSource).toContain('.event-filter-row button.active{border-color:color-mix(in srgb,var(--nvr-blue) 56%,var(--nvr-border));color:var(--nvr-text)')
    expect(timelineSource).toMatch(/\.timeline-playhead\{[^}]*background:var\(--nvr-blue\)/)
    expect(timelineSource).toMatch(/\.timeline-playhead span\{[^}]*background:var\(--nvr-blue\);color:#fff/)
  })
})