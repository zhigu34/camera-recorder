import { describe, expect, it } from 'vitest'

import mainSource from './main.ts?raw'
import workspaceCss from './styles/protect-workspace-unification.css?raw'

describe('Protect workspace visual consistency', () => {
  it('loads the cross-workspace consistency layer after page refinements', () => {
    const detailLayer = mainSource.indexOf("./styles/camera-detail-drawer-v2.css")
    const consistencyLayer = mainSource.indexOf("./styles/protect-workspace-unification.css")

    expect(detailLayer).toBeGreaterThan(-1)
    expect(consistencyLayer).toBeGreaterThan(detailLayer)
  })

  it('covers the five core workspace shells from one shared content rail', () => {
    for (const selector of ['.protect-home', '.protect-live-page', '.events-page', '.camera-page', '.playback-workspace']) {
      expect(workspaceCss).toContain(selector)
    }
    expect(workspaceCss).toContain('--protect-content-max: 1760px')
    expect(workspaceCss).toContain('--protect-page-gutter: 18px')
  })

  it('does not redefine media fitting or start media connections', () => {
    expect(workspaceCss).not.toContain('object-fit')
    expect(workspaceCss).not.toContain('/ws/preview-wall')
    expect(workspaceCss).not.toContain('WebSocket')
  })
})
