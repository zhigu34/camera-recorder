import { describe, expect, it } from 'vitest'

import source from './EventDetectionView.vue?raw'

describe('ONVIF native event source UI', () => {
  it('loads the registered camera.onvif source for the selected camera', () => {
    expect(source).toContain('/event-detection/sources/camera.onvif')
    expect(source).toContain('onvifSource')
  })

  it('requires an explicit user toggle and does not auto-enable the source', () => {
    expect(source).toContain('@change="toggleOnvifSource"')
    expect(source).toContain('{ enabled }')
    expect(source).not.toContain("enabled: true })")
  })

  it('states the duplicate-source boundary in the UI', () => {
    expect(source).toContain('camera.onvif 与 local.motion 不能同时启用')
    expect(source).toContain('ONVIF PullPoint Events')
  })
})
