import { describe, expect, it } from 'vitest'
import eventFeedSource from './PlaybackEventFeed.vue?raw'
import timelineSource from './PlaybackTimelineV3.vue?raw'
import themeSource from './styles/nvr-theme.css?raw'

describe('Playback theme contrast', () => {
  it('uses theme tokens for timeline surfaces and separators', () => {
    expect(timelineSource).toContain('background:var(--nvr-surface)')
    expect(timelineSource).toContain('border-bottom:1px solid var(--nvr-border)')
    expect(timelineSource).toContain('.lane-track{position:relative;margin:6px 0;background:var(--nvr-bg-soft)')
    expect(timelineSource).toContain('.timeline-overview{position:relative;height:18px;margin:10px 0 0 var(--timeline-label-width);border:1px solid var(--nvr-border);border-radius:4px;background:var(--nvr-bg-soft)')
  })

  it('defines soft playback surfaces in both themes', () => {
    expect(themeSource).toContain('--nvr-bg-soft: #10161e;')
    expect(themeSource).toContain('--nvr-bg-soft: #f6f7f9;')
  })

  it('keeps active controls and playhead readable in both themes', () => {
    expect(eventFeedSource).toContain('.event-filter-row button.active{border-color:color-mix(in srgb,var(--nvr-blue) 56%,var(--nvr-border));color:var(--nvr-text)')
    expect(timelineSource).toContain('.timeline-playhead{position:absolute;z-index:5;top:0;bottom:0;width:1px;background:var(--nvr-blue)')
    expect(timelineSource).toContain('.timeline-playhead span{position:absolute;top:-28px;left:50%;transform:translateX(-50%);padding:3px 6px;border-radius:4px;background:var(--nvr-blue);color:#fff')
  })
})